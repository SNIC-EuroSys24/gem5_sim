/*
 * Copyright (c) 2012 Mark D. Hill and David A. Wood
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are
 * met: redistributions of source code must retain the above copyright
 * notice, this list of conditions and the following disclaimer;
 * redistributions in binary form must reproduce the above copyright
 * notice, this list of conditions and the following disclaimer in the
 * documentation and/or other materials provided with the distribution;
 * neither the name of the copyright holders nor the names of its
 * contributors may be used to endorse or promote products derived from
 * this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 * DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 * THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#include "mem/ruby/common/Consumer.hh"
#include "mem/ruby/common/Global.hh"
#include "mem/ruby/system/System.hh"

void
Consumer::scheduleEvent(Time timeDelta)
{
    scheduleEvent(g_system_ptr, timeDelta);
}

void
Consumer::scheduleEvent(EventManager *em, Time timeDelta)
{
    scheduleEventAbsolute(em, timeDelta + g_system_ptr->getTime());
}

void
Consumer::scheduleEventAbsolute(Time timeAbs)
{
    scheduleEventAbsolute(g_system_ptr, timeAbs);
}

void
Consumer::scheduleEventAbsolute(EventManager *em, Time timeAbs)
{
    Tick evt_time = timeAbs * g_system_ptr->getClock();
    if (!alreadyScheduled(evt_time)) {
        // This wakeup is not redundant
        ConsumerEvent *evt = new ConsumerEvent(this);
        assert(timeAbs > g_system_ptr->getTime());

        em->schedule(evt, evt_time);
        insertScheduledWakeupTime(evt_time);
    }
}
