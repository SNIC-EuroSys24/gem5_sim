# Copyright (c) 1999-2008 Mark D. Hill and David A. Wood
# Copyright (c) 2009 The Hewlett-Packard Development Company
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

from slicc.ast.ExprAST import ExprAST
from slicc.symbols import Func, Type

class FuncCallExprAST(ExprAST):
    def __init__(self, slicc, proc_name, exprs):
        super(FuncCallExprAST, self).__init__(slicc)
        self.proc_name = proc_name
        self.exprs = exprs

    def __repr__(self):
        return "[FuncCallExpr: %s %s]" % (self.proc_name, self.exprs)

    def generate(self, code):
        machine = self.state_machine

        if self.proc_name == "DPRINTF":
            # Code for inserting the location of the DPRINTF()
            # statement in the .sm file in the statement it self.
            # 'self.exprs[0].location' represents the location.
            # 'format' represents the second argument of the
            # original DPRINTF() call. It is left unmodified.
            # str_list is used for concatenating the argument
            # list following the format specifier. A DPRINTF()
            # call may or may not contain any arguments following
            # the format specifier. These two cases need to be
            # handled differently. Hence the check whether or not
            # the str_list is empty.

            format = "%s" % (self.exprs[1].inline())
            format_length = len(format)
            str_list = []

            for i in range(2, len(self.exprs)):
                str_list.append("%s" % self.exprs[i].inline())

            if len(str_list) == 0:
                code('DPRINTF(RubySlicc, "$0: $1")',
                     self.exprs[0].location, format[2:format_length-2])
            else:
                code('DPRINTF(RubySlicc, "$0: $1", $2)',
                     self.exprs[0].location, format[2:format_length-2],
                     ', '.join(str_list))

            return self.symtab.find("void", Type)

        # hack for adding comments to profileTransition
        if self.proc_name == "APPEND_TRANSITION_COMMENT":
            # FIXME - check for number of parameters
            code("APPEND_TRANSITION_COMMENT($0)", self.exprs[0].inline())
            return self.symtab.find("void", Type)

        # Look up the function in the symbol table
        func = self.symtab.find(self.proc_name, Func)

        # Check the types and get the code for the parameters
        if func is None:
            self.error("Unrecognized function name: '%s'", self.proc_name)

        if len(self.exprs) != len(func.param_types):
            self.error("Wrong number of arguments passed to function : '%s'" +\
                       " Expected %d, got %d", self.proc_name,
                       len(func.param_types), len(self.exprs))

        cvec = []
        type_vec = []
        for expr,expected_type in zip(self.exprs, func.param_types):
            # Check the types of the parameter
            actual_type,param_code = expr.inline(True)
            if str(actual_type) != str(expected_type):
                expr.error("Type mismatch: expected: %s actual: %s" % \
                           (expected_type, actual_type))
            cvec.append(param_code)
            type_vec.append(expected_type)

        # OK, the semantics of "trigger" here is that, ports in the
        # machine have different priorities. We always check the first
        # port for doable transitions. If nothing/stalled, we pick one
        # from the next port.
        #
        # One thing we have to be careful as the SLICC protocol
        # writter is : If a port have two or more transitions can be
        # picked from in one cycle, they must be independent.
        # Otherwise, if transition A and B mean to be executed in
        # sequential, and A get stalled, transition B can be issued
        # erroneously. In practice, in most case, there is only one
        # transition should be executed in one cycle for a given
        # port. So as most of current protocols.

        if self.proc_name == "trigger":
            code('''
{
    Address addr = ${{cvec[1]}};
''')
            if machine.TBEType != None and machine.EntryType != None:
                code('''
    TransitionResult result = doTransition(${{cvec[0]}}, ${{cvec[2]}}, ${{cvec[3]}}, addr);
''')
            elif machine.TBEType != None:
                code('''
    TransitionResult result = doTransition(${{cvec[0]}}, ${{cvec[2]}}, addr);
''')
            elif machine.EntryType != None:
                code('''
    TransitionResult result = doTransition(${{cvec[0]}}, ${{cvec[2]}}, addr);
''')
            else:
                code('''
    TransitionResult result = doTransition(${{cvec[0]}}, addr);
''')

            code('''
    if (result == TransitionResult_Valid) {
        counter++;
        continue; // Check the first port again
    }

    if (result == TransitionResult_ResourceStall) {
        scheduleEvent(this, 1);

        // Cannot do anything with this transition, go check next doable transition (mostly likely of next port)
    }
}
''')
        elif self.proc_name == "doubleTrigger":
            # NOTE:  Use the doubleTrigger call with extreme caution
            # the key to double trigger is the second event triggered
            # cannot fail becuase the first event cannot be undone
            assert len(cvec) == 4
            code('''
{
    Address addr1 = ${{cvec[1]}};
    TransitionResult result1 =
        doTransition(${{cvec[0]}}, ${machine}_getState(addr1), addr1);

    if (result1 == TransitionResult_Valid) {
        //this second event cannont fail because the first event
        // already took effect
        Address addr2 = ${{cvec[3]}};
        TransitionResult result2 = doTransition(${{cvec[2]}}, ${machine}_getState(addr2), addr2);

        // ensure the event suceeded
        assert(result2 == TransitionResult_Valid);

        counter++;
        continue; // Check the first port again
    }

    if (result1 == TransitionResult_ResourceStall) {
        scheduleEvent(this, 1);
        // Cannot do anything with this transition, go check next
        // doable transition (mostly likely of next port)
    }
}
''')
        elif self.proc_name == "error":
            code("$0", self.exprs[0].embedError(cvec[0]))
        elif self.proc_name == "assert":
            error = self.exprs[0].embedError('"assert failure"')
            code('''
#ifndef NDEBUG
if (!(${{cvec[0]}})) {
    $error
}
#endif
''')

        elif self.proc_name == "continueProcessing":
            code("counter++;")
            code("continue; // Check the first port again")

        elif self.proc_name == "set_cache_entry":
            code("set_cache_entry(m_cache_entry_ptr, %s);" %(cvec[0]));
        elif self.proc_name == "unset_cache_entry":
            code("unset_cache_entry(m_cache_entry_ptr);");
        elif self.proc_name == "set_tbe":
            code("set_tbe(m_tbe_ptr, %s);" %(cvec[0]));
        elif self.proc_name == "unset_tbe":
            code("unset_tbe(m_tbe_ptr);");

        else:
            # Normal function

            # if the func is internal to the chip but not the machine
            # then it can only be accessed through the chip pointer
            internal = ""
            if "external" not in func and not func.isInternalMachineFunc:
                internal = "m_chip_ptr->"

            params = ""
            first_param = True

            for (param_code, type) in zip(cvec, type_vec):
                if first_param:
                    params = str(param_code)
                    first_param  = False
                else:
                    params += ', '
                    params += str(param_code);

            fix = code.nofix()
            code('(${internal}${{func.c_ident}}($params))')
            code.fix(fix)

        return func.return_type
