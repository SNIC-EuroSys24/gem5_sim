# Copyright (c) 2006-2008 The Regents of The University of Michigan
# Copyright (c) 2010 Advanced Micro Devices, Inc.
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met: redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer;
# redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution;
# neither the name of the copyright holders nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# Authors: Lisa Hsu

from os import getcwd
from os.path import join as joinpath

import m5
from m5.defines import buildEnv
from m5.objects import *
from m5.util import *
from O3_ARM_v7a import *

addToPath('../common')

def getCPUClass(cpu_type):
    """Returns the required cpu class and the mode of operation.
    """

    if cpu_type == "timing":
        return TimingSimpleCPU, 'timing'
    elif cpu_type == "detailed":
        return DerivO3CPU, 'timing'
    elif cpu_type == "arm_detailed":
        return O3_ARM_v7a_3, 'timing'
    elif cpu_type == "inorder":
        return InOrderCPU, 'timing'
    else:
        return AtomicSimpleCPU, 'atomic'

def setCPUClass(options):
    """Returns two cpu classes and the initial mode of operation.

       Restoring from a checkpoint or fast forwarding through a benchmark
       can be done using one type of cpu, and then the actual
       simulation can be carried out using another type. This function
       returns these two types of cpus and the initial mode of operation
       depending on the options provided.
    """

    if options.cpu_type == "detailed" or \
       options.cpu_type == "arm_detailed" or \
       options.cpu_type == "inorder" :
        if not options.caches and not options.ruby:
            fatal("O3/Inorder CPU must be used with caches")

    TmpClass, test_mem_mode = getCPUClass(options.cpu_type)
    CPUClass = None

    if options.checkpoint_restore != None:
        if options.restore_with_cpu != options.cpu_type:
            CPUClass = TmpClass
            TmpClass, test_mem_mode = getCPUClass(options.restore_with_cpu)
    elif options.fast_forward:
        CPUClass = TmpClass
        TmpClass = AtomicSimpleCPU
        test_mem_mode = 'atomic'

    return (TmpClass, test_mem_mode, CPUClass)

def setWorkCountOptions(system, options):
    if options.work_item_id != None:
        system.work_item_id = options.work_item_id
    if options.work_begin_cpu_id_exit != None:
        system.work_begin_cpu_id_exit = options.work_begin_cpu_id_exit
    if options.work_end_exit_count != None:
        system.work_end_exit_count = options.work_end_exit_count
    if options.work_end_checkpoint_count != None:
        system.work_end_ckpt_count = options.work_end_checkpoint_count
    if options.work_begin_exit_count != None:
        system.work_begin_exit_count = options.work_begin_exit_count
    if options.work_begin_checkpoint_count != None:
        system.work_begin_ckpt_count = options.work_begin_checkpoint_count
    if options.work_cpus_checkpoint_count != None:
        system.work_cpus_ckpt_count = options.work_cpus_checkpoint_count

def findCptDir(options, maxtick, cptdir, testsys):
    """Figures out the directory from which the checkpointed state is read.

    There are two different ways in which the directories holding checkpoints
    can be named --
    1. cpt.<benchmark name>.<instruction count when the checkpoint was taken>
    2. cpt.<some number, usually the tick value when the checkpoint was taken>

    This function parses through the options to figure out which one of the
    above should be used for selecting the checkpoint, and then figures out
    the appropriate directory.

    It also sets the value of the maximum tick value till which the simulation
    will run.
    """

    from os.path import isdir, exists
    from os import listdir
    import re

    if not isdir(cptdir):
        fatal("checkpoint dir %s does not exist!", cptdir)

    if options.at_instruction or options.simpoint:
        inst = options.checkpoint_restore
        if options.simpoint:
            # assume workload 0 has the simpoint
            if testsys.cpu[0].workload[0].simpoint == 0:
                fatal('Unable to find simpoint')
            inst += int(testsys.cpu[0].workload[0].simpoint)

        checkpoint_dir = joinpath(cptdir, "cpt.%s.%s" % (options.bench, inst))
        if not exists(checkpoint_dir):
            fatal("Unable to find checkpoint directory %s", checkpoint_dir)
    else:
        dirs = listdir(cptdir)
        expr = re.compile('cpt\.([0-9]*)')
        cpts = []
        for dir in dirs:
            match = expr.match(dir)
            if match:
                cpts.append(match.group(1))

        cpts.sort(lambda a,b: cmp(long(a), long(b)))

        cpt_num = options.checkpoint_restore
        if cpt_num > len(cpts):
            fatal('Checkpoint %d not found', cpt_num)

        maxtick = maxtick - int(cpts[cpt_num - 1])
        checkpoint_dir = joinpath(cptdir, "cpt.%s" % cpts[cpt_num - 1])

    return maxtick, checkpoint_dir

def scriptCheckpoints(options, cptdir):
    if options.at_instruction or options.simpoint:
        checkpoint_inst = int(options.take_checkpoints)

        # maintain correct offset if we restored from some instruction
        if options.checkpoint_restore != None:
            checkpoint_inst += options.checkpoint_restore

        print "Creating checkpoint at inst:%d" % (checkpoint_inst)
        exit_event = m5.simulate()
        exit_cause = exit_event.getCause()
        print "exit cause = %s" % exit_cause

        # skip checkpoint instructions should they exist
        while exit_cause == "checkpoint":
            exit_event = m5.simulate()
            exit_cause = exit_event.getCause()

        if exit_cause == "a thread reached the max instruction count":
            m5.checkpoint(joinpath(cptdir, "cpt.%s.%d" % \
                    (options.bench, checkpoint_inst)))
            print "Checkpoint written."

    else:
        when, period = options.take_checkpoints.split(",", 1)
        when = int(when)
        period = int(period)
        num_checkpoints = 0

        exit_event = m5.simulate(when)
        exit_cause = exit_event.getCause()
        while exit_cause == "checkpoint":
            exit_event = m5.simulate(when - m5.curTick())
            exit_cause = exit_event.getCause()

        if exit_cause == "simulate() limit reached":
            m5.checkpoint(joinpath(cptdir, "cpt.%d"))
            num_checkpoints += 1

        sim_ticks = when
        max_checkpoints = options.max_checkpoints

        while num_checkpoints < max_checkpoints and \
                exit_cause == "simulate() limit reached":
            if (sim_ticks + period) > maxtick:
                exit_event = m5.simulate(maxtick - sim_ticks)
                exit_cause = exit_event.getCause()
                break
            else:
                exit_event = m5.simulate(period)
                exit_cause = exit_event.getCause()
                sim_ticks += period
                while exit_event.getCause() == "checkpoint":
                    exit_event = m5.simulate(sim_ticks - m5.curTick())
                if exit_event.getCause() == "simulate() limit reached":
                    m5.checkpoint(joinpath(cptdir, "cpt.%d"))
                    num_checkpoints += 1

    return exit_cause

def benchCheckpoints(options, maxtick, cptdir, numpids):
    exit_event = m5.simulate(maxtick,numpids)
    exit_cause = exit_event.getCause()

    num_checkpoints = 0
    max_checkpoints = options.max_checkpoints

    while exit_cause == "checkpoint":
        m5.checkpoint(joinpath(cptdir, "cpt.%d"))
        num_checkpoints += 1
        if num_checkpoints == max_checkpoints:
            exit_cause = "maximum %d checkpoints dropped" % max_checkpoints
            break

        exit_event = m5.simulate(maxtick - m5.curTick(),numpids)
        exit_cause = exit_event.getCause()

    return exit_cause

def repeatSwitch(testsys, repeat_switch_cpu_list, maxtick, switch_freq):
    print "starting switch loop"
    while True:
        exit_event = m5.simulate(switch_freq)
        exit_cause = exit_event.getCause()

        if exit_cause != "simulate() limit reached":
            return exit_cause

        print "draining the system"
        m5.doDrain(testsys)
        m5.switchCpus(repeat_switch_cpu_list)
        m5.resume(testsys)

        tmp_cpu_list = []
        for old_cpu, new_cpu in repeat_switch_cpu_list:
            tmp_cpu_list.append((new_cpu, old_cpu))
        repeat_switch_cpu_list = tmp_cpu_list

        if (maxtick - m5.curTick()) <= switch_freq:
            exit_event = m5.simulate(maxtick - m5.curTick())
            return exit_event.getCause()

def run(options, root, testsys, cpu_class):
    run(options, root, testsysm, cpu_class, 2)

def run(options, root, testsys, cpu_class, numpids):
    if options.maxtick:
        maxtick = options.maxtick
    elif options.maxtime:
        simtime = m5.ticks.seconds(simtime)
        print "simulating for: ", simtime
        maxtick = simtime
    else:
        maxtick = m5.MaxTick

    if options.checkpoint_dir:
        cptdir = options.checkpoint_dir
    elif m5.options.outdir:
        cptdir = m5.options.outdir
    else:
        cptdir = getcwd()

    if options.fast_forward and options.checkpoint_restore != None:
        fatal("Can't specify both --fast-forward and --checkpoint-restore")

    if options.standard_switch and not options.caches:
        fatal("Must specify --caches when using --standard-switch")

    if options.standard_switch and options.repeat_switch:
        fatal("Can't specify both --standard-switch and --repeat-switch")

    if options.repeat_switch and options.take_checkpoints:
        fatal("Can't specify both --repeat-switch and --take-checkpoints")

    np = options.num_cpus
    switch_cpus = None

    if options.prog_interval:
        for i in xrange(np):
            testsys.cpu[i].progress_interval = options.prog_interval

    if options.maxinsts:
        for i in xrange(np):
            testsys.cpu[i].max_insts_any_thread = options.maxinsts

    if cpu_class:
        switch_cpus = [cpu_class(defer_registration=True, cpu_id=(i))
                       for i in xrange(np)]

        for i in xrange(np):
            if options.fast_forward:
                testsys.cpu[i].max_insts_any_thread = int(options.fast_forward)
            switch_cpus[i].system =  testsys
            switch_cpus[i].workload = testsys.cpu[i].workload
            switch_cpus[i].clock = testsys.cpu[i].clock
            # simulation period
            if options.maxinsts:
                switch_cpus[i].max_insts_any_thread = options.maxinsts
            # Add checker cpu if selected
            if options.checker:
                switch_cpus[i].addCheckerCpu()

        testsys.switch_cpus = switch_cpus
        switch_cpu_list = [(testsys.cpu[i], switch_cpus[i]) for i in xrange(np)]

    if options.repeat_switch:
        if options.cpu_type == "arm_detailed":
            if not options.caches:
                print "O3 CPU must be used with caches"
                sys.exit(1)

            repeat_switch_cpus = [O3_ARM_v7a_3(defer_registration=True, \
                                  cpu_id=(i)) for i in xrange(np)]
        elif options.cpu_type == "detailed":
            if not options.caches:
                print "O3 CPU must be used with caches"
                sys.exit(1)

            repeat_switch_cpus = [DerivO3CPU(defer_registration=True, \
                                  cpu_id=(i)) for i in xrange(np)]
        elif options.cpu_type == "inorder":
            print "inorder CPU switching not supported"
            sys.exit(1)
        elif options.cpu_type == "timing":
            repeat_switch_cpus = [TimingSimpleCPU(defer_registration=True, \
                                  cpu_id=(i)) for i in xrange(np)]
        else:
            repeat_switch_cpus = [AtomicSimpleCPU(defer_registration=True, \
                                  cpu_id=(i)) for i in xrange(np)]

        for i in xrange(np):
            repeat_switch_cpus[i].system = testsys
            repeat_switch_cpus[i].workload = testsys.cpu[i].workload
            repeat_switch_cpus[i].clock = testsys.cpu[i].clock

            if options.maxinsts:
                repeat_switch_cpus[i].max_insts_any_thread = options.maxinsts

            if options.checker:
                repeat_switch_cpus[i].addCheckerCpu()

        testsys.repeat_switch_cpus = repeat_switch_cpus

        if cpu_class:
            repeat_switch_cpu_list = [(switch_cpus[i], repeat_switch_cpus[i])
                                      for i in xrange(np)]
        else:
            repeat_switch_cpu_list = [(testsys.cpu[i], repeat_switch_cpus[i])
                                      for i in xrange(np)]

    if options.standard_switch:
        switch_cpus = [TimingSimpleCPU(defer_registration=True, cpu_id=(i))
                       for i in xrange(np)]
        switch_cpus_1 = [DerivO3CPU(defer_registration=True, cpu_id=(i))
                        for i in xrange(np)]

        for i in xrange(np):
            switch_cpus[i].system =  testsys
            switch_cpus_1[i].system =  testsys
            switch_cpus[i].workload = testsys.cpu[i].workload
            switch_cpus_1[i].workload = testsys.cpu[i].workload
            switch_cpus[i].clock = testsys.cpu[i].clock
            switch_cpus_1[i].clock = testsys.cpu[i].clock

            # if restoring, make atomic cpu simulate only a few instructions
            if options.checkpoint_restore != None:
                testsys.cpu[i].max_insts_any_thread = 1
            # Fast forward to specified location if we are not restoring
            elif options.fast_forward:
                testsys.cpu[i].max_insts_any_thread = int(options.fast_forward)
            # Fast forward to a simpoint (warning: time consuming)
            elif options.simpoint:
                if testsys.cpu[i].workload[0].simpoint == 0:
                    fatal('simpoint not found')
                testsys.cpu[i].max_insts_any_thread = \
                    testsys.cpu[i].workload[0].simpoint
            # No distance specified, just switch
            else:
                testsys.cpu[i].max_insts_any_thread = 1

            # warmup period
            if options.warmup_insts:
                switch_cpus[i].max_insts_any_thread =  options.warmup_insts

            # simulation period
            if options.maxinsts:
                switch_cpus_1[i].max_insts_any_thread = options.maxinsts

            # attach the checker cpu if selected
            if options.checker:
                switch_cpus[i].addCheckerCpu()
                switch_cpus_1[i].addCheckerCpu()

        testsys.switch_cpus = switch_cpus
        testsys.switch_cpus_1 = switch_cpus_1
        switch_cpu_list = [(testsys.cpu[i], switch_cpus[i]) for i in xrange(np)]
        switch_cpu_list1 = [(switch_cpus[i], switch_cpus_1[i]) for i in xrange(np)]

    # set the checkpoint in the cpu before m5.instantiate is called
    if options.take_checkpoints != None and \
           (options.simpoint or options.at_instruction):
        offset = int(options.take_checkpoints)
        # Set an instruction break point
        if options.simpoint:
            for i in xrange(np):
                if testsys.cpu[i].workload[0].simpoint == 0:
                    fatal('no simpoint for testsys.cpu[%d].workload[0]', i)
                checkpoint_inst = int(testsys.cpu[i].workload[0].simpoint) + offset
                testsys.cpu[i].max_insts_any_thread = checkpoint_inst
                # used for output below
                options.take_checkpoints = checkpoint_inst
        else:
            options.take_checkpoints = offset
            # Set all test cpus with the right number of instructions
            # for the upcoming simulation
            for i in xrange(np):
                testsys.cpu[i].max_insts_any_thread = offset

    checkpoint_dir = None
    if options.checkpoint_restore != None:
        maxtick, checkpoint_dir = findCptDir(options, maxtick, cptdir, testsys)
    m5.instantiate(checkpoint_dir)

    if options.standard_switch or cpu_class:
        if options.standard_switch:
            print "Switch at instruction count:%s" % \
                    str(testsys.cpu[0].max_insts_any_thread)
            exit_event = m5.simulate(maxtick,numpids)
        elif cpu_class and options.fast_forward:
            print "Switch at instruction count:%s" % \
                    str(testsys.cpu[0].max_insts_any_thread)
            exit_event = m5.simulate(maxtick,numpids)
        else:
            print "Switch at curTick count:%s" % str(10000)
            exit_event = m5.simulate(10000)
        print "Switched CPUS @ tick %s" % (m5.curTick())

        # when you change to Timing (or Atomic), you halt the system
        # given as argument.  When you are finished with the system
        # changes (including switchCpus), you must resume the system
        # manually.  You DON'T need to resume after just switching
        # CPUs if you haven't changed anything on the system level.

        m5.changeToTiming(testsys)
        m5.switchCpus(switch_cpu_list)
        m5.resume(testsys)

        if options.standard_switch:
            print "Switch at instruction count:%d" % \
                    (testsys.switch_cpus[0].max_insts_any_thread)

            #warmup instruction count may have already been set
            if options.warmup_insts:
                exit_event = m5.simulate(maxtick,numpids)
            else:
                exit_event = m5.simulate(options.standard_switch,numpids)
            print "Switching CPUS @ tick %s" % (m5.curTick())
            print "Simulation ends instruction count:%d" % \
                    (testsys.switch_cpus_1[0].max_insts_any_thread)
            m5.drain(testsys)
            m5.switchCpus(switch_cpu_list1)
            m5.resume(testsys)

    # If we're taking and restoring checkpoints, use checkpoint_dir
    # option only for finding the checkpoints to restore from.  This
    # lets us test checkpointing by restoring from one set of
    # checkpoints, generating a second set, and then comparing them.
    if options.take_checkpoints and options.checkpoint_restore:
        if m5.options.outdir:
            cptdir = m5.options.outdir
        else:
            cptdir = getcwd()

    if options.take_checkpoints != None :
        # Checkpoints being taken via the command line at <when> and at
        # subsequent periods of <period>.  Checkpoint instructions
        # received from the benchmark running are ignored and skipped in
        # favor of command line checkpoint instructions.
        exit_cause = scriptCheckpoints(options, cptdir)
    else:
        if options.fast_forward:
            m5.stats.reset()
        print "**** REAL SIMULATION ****"

        # If checkpoints are being taken, then the checkpoint instruction
        # will occur in the benchmark code it self.
        if options.repeat_switch and maxtick > options.repeat_switch:
            exit_cause = repeatSwitch(testsys, repeat_switch_cpu_list,
                                      maxtick, options.repeat_switch)
        else:
            exit_cause = benchCheckpoints(options, maxtick, cptdir, numpids)

    print 'Exiting @ tick %i because %s' % (m5.curTick(), exit_cause)
    if options.checkpoint_at_end:
        m5.checkpoint(joinpath(cptdir, "cpt.%d"))
