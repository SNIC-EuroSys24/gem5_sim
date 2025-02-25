/*
 * Copyright (c) 2011-2012 ARM Limited
 * All rights reserved
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
 * Copyright (c) 2006 The Regents of The University of Michigan
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
 * Authors: Ali Saidi
 *          Steve Reinhardt
 *          Andreas Hansson
 */

/**
 * @file
 * Declaration of a memory-mapped bus bridge that connects a master
 * and a slave through a request and response queue.
 */

#ifndef __MEM_BRIDGE_HH__
#define __MEM_BRIDGE_HH__

#include <list>

#include "base/types.hh"
#include "mem/mem_object.hh"
#include "params/Bridge.hh"

/**
 * A bridge is used to interface two different busses (or in general a
 * memory-mapped master and slave), with buffering for requests and
 * responses. The bridge has a fixed delay for packets passing through
 * it and responds to a fixed set of address ranges.
 *
 * The bridge comprises a slave port and a master port, that buffer
 * outgoing responses and requests respectively. Buffer space is
 * reserved when a request arrives, also reserving response space
 * before forwarding the request. If there is no space present, then
 * the bridge will delay accepting the packet until space becomes
 * available.
 */
class Bridge : public MemObject
{
  protected:

    /**
     * A bridge request state stores packets along with their sender
     * state and original source. It has enough information to also
     * restore the response once it comes back to the bridge.
     */
    class RequestState : public Packet::SenderState
    {

      public:

        Packet::SenderState *origSenderState;
        PortID origSrc;

        RequestState(PacketPtr _pkt)
            : origSenderState(_pkt->senderState),
              origSrc(_pkt->getSrc())
        { }

        void fixResponse(PacketPtr pkt)
        {
            assert(pkt->senderState == this);
            pkt->setDest(origSrc);
            pkt->senderState = origSenderState;
        }
    };

    /**
     * A deferred packet stores a packet along with its scheduled
     * transmission time
     */
    class DeferredPacket
    {

      public:

        Tick tick;
        PacketPtr pkt;

        DeferredPacket(PacketPtr _pkt, Tick _tick) : tick(_tick), pkt(_pkt)
        { }
    };

    // Forward declaration to allow the slave port to have a pointer
    class BridgeMasterPort;

    /**
     * The port on the side that receives requests and sends
     * responses. The slave port has a set of address ranges that it
     * is responsible for. The slave port also has a buffer for the
     * responses not yet sent.
     */
    class BridgeSlavePort : public SlavePort
    {

      private:

        /** The bridge to which this port belongs. */
        Bridge& bridge;

        /**
         * Master port on the other side of the bridge (connected to
         * the other bus).
         */
        BridgeMasterPort& masterPort;

        /** Minimum request delay though this bridge. */
        Cycles delay;

        /** Address ranges to pass through the bridge */
        AddrRangeList ranges;

        /**
         * Response packet queue. Response packets are held in this
         * queue for a specified delay to model the processing delay
         * of the bridge.
         */
        std::list<DeferredPacket> transmitList;

        /** Counter to track the outstanding responses. */
        unsigned int outstandingResponses;

        /** If we should send a retry when space becomes available. */
        bool retryReq;

        /** Max queue size for reserved responses. */
        unsigned int respQueueLimit;

        /**
         * Is this side blocked from accepting new response packets.
         *
         * @return true if the reserved space has reached the set limit
         */
        bool respQueueFull();

        /**
         * Handle send event, scheduled when the packet at the head of
         * the response queue is ready to transmit (for timing
         * accesses only).
         */
        void trySendTiming();

        /** Send event for the response queue. */
        EventWrapper<BridgeSlavePort,
                     &BridgeSlavePort::trySendTiming> sendEvent;

      public:

        /**
         * Constructor for the BridgeSlavePort.
         *
         * @param _name the port name including the owner
         * @param _bridge the structural owner
         * @param _masterPort the master port on the other side of the bridge
         * @param _delay the delay in cycles from receiving to sending
         * @param _resp_limit the size of the response queue
         * @param _ranges a number of address ranges to forward
         */
        BridgeSlavePort(const std::string& _name, Bridge& _bridge,
                        BridgeMasterPort& _masterPort, Cycles _delay,
                        int _resp_limit, std::vector<Range<Addr> > _ranges);

        /**
         * Queue a response packet to be sent out later and also schedule
         * a send if necessary.
         *
         * @param pkt a response to send out after a delay
         * @param when tick when response packet should be sent
         */
        void schedTimingResp(PacketPtr pkt, Tick when);

        /**
         * Retry any stalled request that we have failed to accept at
         * an earlier point in time. This call will do nothing if no
         * request is waiting.
         */
        void retryStalledReq();

      protected:

        /** When receiving a timing request from the peer port,
            pass it to the bridge. */
        bool recvTimingReq(PacketPtr pkt);

        /** When receiving a retry request from the peer port,
            pass it to the bridge. */
        void recvRetry();

        /** When receiving a Atomic requestfrom the peer port,
            pass it to the bridge. */
        Tick recvAtomic(PacketPtr pkt);

        /** When receiving a Functional request from the peer port,
            pass it to the bridge. */
        void recvFunctional(PacketPtr pkt);

        /** When receiving a address range request the peer port,
            pass it to the bridge. */
        AddrRangeList getAddrRanges() const;
    };


    /**
     * Port on the side that forwards requests and receives
     * responses. The master port has a buffer for the requests not
     * yet sent.
     */
    class BridgeMasterPort : public MasterPort
    {

      private:

        /** The bridge to which this port belongs. */
        Bridge& bridge;

        /**
         * The slave port on the other side of the bridge (connected
         * to the other bus).
         */
        BridgeSlavePort& slavePort;

        /** Minimum delay though this bridge. */
        Cycles delay;

        /**
         * Request packet queue. Request packets are held in this
         * queue for a specified delay to model the processing delay
         * of the bridge.
         */
        std::list<DeferredPacket> transmitList;

        /** Max queue size for request packets */
        unsigned int reqQueueLimit;

        /**
         * Handle send event, scheduled when the packet at the head of
         * the outbound queue is ready to transmit (for timing
         * accesses only).
         */
        void trySendTiming();

        /** Send event for the request queue. */
        EventWrapper<BridgeMasterPort,
                     &BridgeMasterPort::trySendTiming> sendEvent;

      public:

        /**
         * Constructor for the BridgeMasterPort.
         *
         * @param _name the port name including the owner
         * @param _bridge the structural owner
         * @param _slavePort the slave port on the other side of the bridge
         * @param _delay the delay in cycles from receiving to sending
         * @param _req_limit the size of the request queue
         */
        BridgeMasterPort(const std::string& _name, Bridge& _bridge,
                         BridgeSlavePort& _slavePort, Cycles _delay,
                         int _req_limit);

        /**
         * Is this side blocked from accepting new request packets.
         *
         * @return true if the occupied space has reached the set limit
         */
        bool reqQueueFull();

        /**
         * Queue a request packet to be sent out later and also schedule
         * a send if necessary.
         *
         * @param pkt a request to send out after a delay
         * @param when tick when response packet should be sent
         */
        void schedTimingReq(PacketPtr pkt, Tick when);

        /**
         * Check a functional request against the packets in our
         * request queue.
         *
         * @param pkt packet to check against
         *
         * @return true if we find a match
         */
        bool checkFunctional(PacketPtr pkt);

      protected:

        /** When receiving a timing request from the peer port,
            pass it to the bridge. */
        bool recvTimingResp(PacketPtr pkt);

        /** When receiving a retry request from the peer port,
            pass it to the bridge. */
        void recvRetry();
    };

    /** Slave port of the bridge. */
    BridgeSlavePort slavePort;

    /** Master port of the bridge. */
    BridgeMasterPort masterPort;

  public:

    virtual MasterPort& getMasterPort(const std::string& if_name,
                                      int idx = -1);
    virtual SlavePort& getSlavePort(const std::string& if_name, int idx = -1);

    virtual void init();

    typedef BridgeParams Params;

    Bridge(Params *p);
};

#endif //__MEM_BUS_HH__
