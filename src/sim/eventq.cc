/*
 * Copyright (c) 2000-2005 The Regents of The University of Michigan
 * Copyright (c) 2008 The Hewlett-Packard Development Company
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
 *
 * Authors: Steve Reinhardt
 *          Nathan Binkert
 *          Steve Raasch
 */

#include <cassert>
#include <iostream>
#include <string>
#include <vector>

#include "base/hashmap.hh"
#include "base/misc.hh"
#include "base/trace.hh"
#include "cpu/smt.hh"
#include "debug/Config.hh"
#include "sim/core.hh"
#include "sim/eventq.hh"
#include "sim/global_exit_count.hh"

using namespace std;

//
// Main Event Queue
//
// Events on this queue are processed at the *beginning* of each
// cycle, before the pipeline simulation is performed.
//
EventQueue mainEventQueue("Main Event Queue");

#ifndef NDEBUG
Counter Event::instanceCounter = 0;
#endif

Event::~Event()
{
    assert(!scheduled());
    flags = 0;
}

const std::string
Event::name() const
{
#ifndef NDEBUG
    return csprintf("Event_%d", instance);
#else
    return csprintf("Event_%x", (uintptr_t)this);
#endif
}


Event *
Event::insertBefore(Event *event, Event *curr)
{
    // Either way, event will be the top element in the 'in bin' list
    // which is the pointer we need in order to look into the list, so
    // we need to insert that into the bin list.
    if (!curr || *event < *curr) {
        // Insert the event before the current list since it is in the future.
        event->nextBin = curr;
        event->nextInBin = NULL;
    } else {
        // Since we're on the correct list, we need to point to the next list
        event->nextBin = curr->nextBin;  // curr->nextBin can now become stale

        // Insert event at the top of the stack
        event->nextInBin = curr;
    }

    return event;
}

void
EventQueue::insert(Event *event)
{
    // Deal with the head case
    if (!head || *event <= *head) {
        head = Event::insertBefore(event, head);
        return;
    }

    // Figure out either which 'in bin' list we are on, or where a new list
    // needs to be inserted
    Event *prev = head;
    Event *curr = head->nextBin;
    while (curr && *curr < *event) {
        prev = curr;
        curr = curr->nextBin;
    }

    // Note: this operation may render all nextBin pointers on the
    // prev 'in bin' list stale (except for the top one)
    prev->nextBin = Event::insertBefore(event, curr);
}

Event *
Event::removeItem(Event *event, Event *top)
{
    Event *curr = top;
    Event *next = top->nextInBin;

    // if we removed the top item, we need to handle things specially
    // and just remove the top item, fixing up the next bin pointer of
    // the new top item
    if (event == top) {
        if (!next)
            return top->nextBin;
        next->nextBin = top->nextBin;
        return next;
    }

    // Since we already checked the current element, we're going to
    // keep checking event against the next element.
    while (event != next) {
        if (!next)
            panic("event not found!");

        curr = next;
        next = next->nextInBin;
    }

    // remove next from the 'in bin' list since it's what we're looking for
    curr->nextInBin = next->nextInBin;
    return top;
}

void
EventQueue::remove(Event *event)
{
    if (head == NULL)
        panic("event not found!");

    // deal with an event on the head's 'in bin' list (event has the same
    // time as the head)
    if (*head == *event) {
        head = Event::removeItem(event, head);
        return;
    }

    // Find the 'in bin' list that this event belongs on
    Event *prev = head;
    Event *curr = head->nextBin;
    while (curr && *curr < *event) {
        prev = curr;
        curr = curr->nextBin;
    }

    if (!curr || *curr != *event)
        panic("event not found!");

    // curr points to the top item of the the correct 'in bin' list, when
    // we remove an item, it returns the new top item (which may be
    // unchanged)
    prev->nextBin = Event::removeItem(event, curr);
}

Event *
EventQueue::serviceOne()
{
    Event *event = head;
    Event *next = head->nextInBin;
    event->flags.clear(Event::Scheduled);

    if (next) {
        // update the next bin pointer since it could be stale
        next->nextBin = head->nextBin;

        // pop the stack
        head = next;
    } else {
        // this was the only element on the 'in bin' list, so get rid of
        // the 'in bin' list and point to the next bin list
        head = head->nextBin;
    }

    // handle action
    if (!event->squashed()) {
        event->process();
        if (event->isExitEvent()) {
            assert(!event->flags.isSet(Event::AutoDelete)); // would be silly
            return event;
        }
    } else {
        event->flags.clear(Event::Squashed);
    }

    if (event->flags.isSet(Event::AutoDelete) && !event->scheduled())
        delete event;

    return NULL;
}

void
Event::serialize(std::ostream &os)
{
    SERIALIZE_SCALAR(_when);
    SERIALIZE_SCALAR(_priority);
    short _flags = flags;
    SERIALIZE_SCALAR(_flags);
}

void
Event::unserialize(Checkpoint *cp, const string &section)
{
    if (scheduled())
        mainEventQueue.deschedule(this);

    UNSERIALIZE_SCALAR(_when);
    UNSERIALIZE_SCALAR(_priority);

    short _flags;
    UNSERIALIZE_SCALAR(_flags);

    // Old checkpoints had no concept of the Initialized flag
    // so restoring from old checkpoints always fail.
    // Events are initialized on construction but original code 
    // "flags = _flags" would just overwrite the initialization. 
    // So, read in the checkpoint flags, but then set the Initialized 
    // flag on top of it in order to avoid failures.
    assert(initialized());
    flags = _flags;
    flags.set(Initialized);

    // need to see if original event was in a scheduled, unsquashed
    // state, but don't want to restore those flags in the current
    // object itself (since they aren't immediately true)
    bool wasScheduled = flags.isSet(Scheduled) && !flags.isSet(Squashed);
    flags.clear(Squashed | Scheduled);

    if (wasScheduled) {
        DPRINTF(Config, "rescheduling at %d\n", _when);
        mainEventQueue.schedule(this, _when);
    }
}

void
EventQueue::serialize(ostream &os)
{
    std::list<Event *> eventPtrs;

    int numEvents = 0;
    Event *nextBin = head;
    while (nextBin) {
        Event *nextInBin = nextBin;

        while (nextInBin) {
            if (nextInBin->flags.isSet(Event::AutoSerialize)) {
                eventPtrs.push_back(nextInBin);
                paramOut(os, csprintf("event%d", numEvents++),
                         nextInBin->name());
            }
            nextInBin = nextInBin->nextInBin;
        }

        nextBin = nextBin->nextBin;
    }

    SERIALIZE_SCALAR(numEvents);

    for (std::list<Event *>::iterator it = eventPtrs.begin();
         it != eventPtrs.end(); ++it) {
        (*it)->nameOut(os);
        (*it)->serialize(os);
    }
}

void
EventQueue::unserialize(Checkpoint *cp, const std::string &section)
{
    int numEvents;
    UNSERIALIZE_SCALAR(numEvents);

    std::string eventName;
    for (int i = 0; i < numEvents; i++) {
        // get the pointer value associated with the event
        paramIn(cp, section, csprintf("event%d", i), eventName);

        // create the event based on its pointer value
        Serializable::create(cp, eventName);
    }
}

void
EventQueue::dump() const
{
    cprintf("============================================================\n");
    cprintf("EventQueue Dump  (cycle %d)\n", curTick());
    cprintf("------------------------------------------------------------\n");

    if (empty())
        cprintf("<No Events>\n");
    else {
        Event *nextBin = head;
        while (nextBin) {
            Event *nextInBin = nextBin;
            while (nextInBin) {
                nextInBin->dump();
                nextInBin = nextInBin->nextInBin;
            }

            nextBin = nextBin->nextBin;
        }
    }

    cprintf("============================================================\n");
}

bool
EventQueue::debugVerify() const
{
    m5::hash_map<long, bool> map;

    Tick time = 0;
    short priority = 0;

    Event *nextBin = head;
    while (nextBin) {
        Event *nextInBin = nextBin;
        while (nextInBin) {
            if (nextInBin->when() < time) {
                cprintf("time goes backwards!");
                nextInBin->dump();
                return false;
            } else if (nextInBin->when() == time &&
                       nextInBin->priority() < priority) {
                cprintf("priority inverted!");
                nextInBin->dump();
                return false;
            }

            if (map[reinterpret_cast<long>(nextInBin)]) {
                cprintf("Node already seen");
                nextInBin->dump();
                return false;
            }
            map[reinterpret_cast<long>(nextInBin)] = true;

            time = nextInBin->when();
            priority = nextInBin->priority();

            nextInBin = nextInBin->nextInBin;
        }

        nextBin = nextBin->nextBin;
    }

    return true;
}

Event*
EventQueue::replaceHead(Event* s)
{
    Event* t = head;
    head = s;
    return t;
}

void
dumpMainQueue()
{
    mainEventQueue.dump();
}


const char *
Event::description() const
{
    return "generic";
}

void
Event::trace(const char *action)
{
    // This DPRINTF is unconditional because calls to this function
    // are protected by an 'if (DTRACE(Event))' in the inlined Event
    // methods.
    //
    // This is just a default implementation for derived classes where
    // it's not worth doing anything special.  If you want to put a
    // more informative message in the trace, override this method on
    // the particular subclass where you have the information that
    // needs to be printed.
    DPRINTFN("%s event %s @ %d\n", description(), action, when());
}

void
Event::dump() const
{
    cprintf("Event %s (%s)\n", name(), description());
    cprintf("Flags: %#x\n", flags);
#ifdef EVENTQ_DEBUG
    cprintf("Created: %d\n", whenCreated);
#endif
    if (scheduled()) {
#ifdef EVENTQ_DEBUG
        cprintf("Scheduled at  %d\n", whenScheduled);
#endif
        cprintf("Scheduled for %d, priority %d\n", when(), _priority);
    } else {
        cprintf("Not Scheduled\n");
    }
}

EventQueue::EventQueue(const string &n)
    : objName(n), head(NULL)
{
    exit_count=2;
}
