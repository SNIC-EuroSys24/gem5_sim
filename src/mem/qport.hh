/*
 * Copyright (c) 2012 ARM Limited
 * All rights reserved.
 *
 * The license below extends only to copyright in the software and shall
 * not be construed as granting a license to any other intellectual
 * property including but not limited to intellectual property relating
 * to a hardware implementation of the functionality of the software
 * licensed hereunder.  You may use the software subject to the license
 * terms below provided that you ensure that this notice is replicated
 * unmodified and in its entirety in all distributions of the software,
 * modified or unmodified, in source code or in binary form.
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
 * Authors: Andreas Hansson
 */

#ifndef __MEM_QPORT_HH__
#define __MEM_QPORT_HH__

/**
 * @file
 * Declaration of the queued port.
 */

#include "mem/packet_queue.hh"
#include "mem/port.hh"

/**
 * A queued port is a port that has an infinite queue for outgoing
 * packets and thus decouples the module that wants to send
 * request/responses from the flow control (retry mechanism) of the
 * port. A queued port can be used by both a master and a slave. The
 * queue is a parameter to allow tailoring of the queue implementation
 * (used in the cache).
 */
class QueuedSlavePort : public SlavePort
{

  protected:

    /** Packet queue used to store outgoing requests and responses. */
    SlavePacketQueue &queue;

     /** This function is notification that the device should attempt to send a
      * packet again. */
    virtual void recvRetry() { queue.retry(); }
	
	virtual void recvRetry(int threadID) { recvRetry(); }

  public:

	/**
     * Create a QueuedPort with a given name, owner, and a supplied
     * implementation of a packet queue. The external definition of
     * the queue enables e.g. the cache to implement a specific queue
     * behaviuor in a subclass, and provide the latter to the
     * QueuePort constructor.
     */
    QueuedSlavePort(const std::string& name, MemObject* owner,
                    SlavePacketQueue &queue) :
        SlavePort(name, owner), queue(queue)
    { }

    virtual ~QueuedSlavePort() { }

    /**
     * Schedule the sending of a timing response.
     *
     * @param pkt Packet to send
     * @param when Absolute time (in ticks) to send packet
     */
    virtual void schedTimingResp(PacketPtr pkt, Tick when)
	{ queue.schedSendTiming(pkt, when); }
	
    virtual void schedTimingResp(PacketPtr pkt, Tick when, int threadID)
    { schedTimingResp( pkt, when ); }

    /** Check the list of buffered packets against the supplied
     * functional request. */
    bool checkFunctional(PacketPtr pkt) { return queue.checkFunctional(pkt); }

    /**
     * Hook for draining the queued port.
     *
     * @param de an event which is used to signal back to the caller
     * @returns a number indicating how many times process will be called
     */
    unsigned int drain(Event *de) { return queue.drain(de); }
};

class QueuedMasterPort : public MasterPort
{

  protected:

    /** Packet queue used to store outgoing requests and responses. */
    MasterPacketQueue &queue;

     /** This function is notification that the device should attempt to send a
      * packet again. */
    virtual void recvRetry() { queue.retry(); }
	
	virtual void recvRetry(int threadID) { recvRetry(); }

  public:

	/**
     * Create a QueuedPort with a given name, owner, and a supplied
     * implementation of a packet queue. The external definition of
     * the queue enables e.g. the cache to implement a specific queue
     * behaviuor in a subclass, and provide the latter to the
     * QueuePort constructor.
     */
    QueuedMasterPort(const std::string& name, MemObject* owner,
                     MasterPacketQueue &queue) :
        MasterPort(name, owner), queue(queue)
    { }

    virtual ~QueuedMasterPort() { }

    /**
     * Schedule the sending of a timing request.
     *
     * @param pkt Packet to send
     * @param when Absolute time (in ticks) to send packet
     */
    void schedTimingReq(PacketPtr pkt, Tick when)
    { queue.schedSendTiming(pkt, when); }

    virtual void schedTimingResp(PacketPtr pkt, Tick when, int threadID){
        schedTimingReq( pkt, when );
    }

    /**
     * Schedule the sending of a timing snoop response.
     *
     * @param pkt Packet to send
     * @param when Absolute time (in ticks) to send packet
     */
    void schedTimingSnoopResp(PacketPtr pkt, Tick when)
    { queue.schedSendTiming(pkt, when, true); }

    /** Check the list of buffered packets against the supplied
     * functional request. */
    bool checkFunctional(PacketPtr pkt) { return queue.checkFunctional(pkt); }

    /**
     * Hook for draining the queued port.
     *
     * @param de an event which is used to signal back to the caller
     * @returns a number indicating how many times process will be called
     */
    unsigned int drain(Event *de) { return queue.drain(de); }
};

#endif // __MEM_QPORT_HH__
