/*********************************************************************************
 *  Copyright (c) 2010-2011, Elliott Cooper-Balis
 *                             Paul Rosenfeld
 *                             Bruce Jacob
 *                             University of Maryland 
 *                             dramninjas [at] gmail [dot] com
 *  All rights reserved.
 *  
 *  Redistribution and use in source and binary forms, with or without
 *  modification, are permitted provided that the following conditions are met:
 *  
 *     * Redistributions of source code must retain the above copyright notice,
 *        this list of conditions and the following disclaimer.
 *  
 *     * Redistributions in binary form must reproduce the above copyright notice,
 *        this list of conditions and the following disclaimer in the documentation
 *        and/or other materials provided with the distribution.
 *  
 *  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
 *  ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 *  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 *  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
 *  FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 *  DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
 *  SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 *  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 *  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *********************************************************************************/
#include "SimulatorObject.h"
#include "Transaction.h"
#include "SystemConfiguration.h"
#include "MemorySystem.h"
#include "IniReader.h"
#include "ClockDomain.h"
#include "CSVWriter.h"


namespace DRAMSim {

    class MultiChannelMemorySystem : public SimulatorObject 
    {
        public: 

            MultiChannelMemorySystem(const string &dev, const string &sys, 
                    unsigned tpTurnLength, bool genTrace,
                    const string &pwd, const string &trc, unsigned megsOfMemory,
                    const string &output, string *visFilename=NULL, 
                    const IniReader::OverrideMap *paramOverrides=NULL,
                    int num_pids=2, bool fixAddr=false,
                    bool diffPeriod=false, int p0Period=64, int p1Period=64, int offset=0);
            virtual ~MultiChannelMemorySystem();
            bool addTransaction(Transaction *trans);
            bool addTransaction(const Transaction &trans);
            bool addTransaction(bool isWrite, uint64_t addr);
            bool willAcceptTransaction(); 
            bool willAcceptTransaction(uint64_t addr); 
            void update();
            void printStats(bool finalStats=false);
            ostream &getLogFile();
            void RegisterCallbacks( 
                    TransactionCompleteCB *readDone,
                    TransactionCompleteCB *writeDone,
                    void (*reportPower)(double bgpower, double burstpower, 
                        double refreshpower, double actprepower)
                    );

            void InitOutputFiles(string tracefilename);
            void setCPUClockSpeed(uint64_t cpuClkFreqHz);

            //output file
            std::ofstream visDataOut;
            ofstream dramsim_log; 
			vector<MemorySystem*> channels; 

        private:
            unsigned findChannelNumber(uint64_t addr);
            void actual_update(); 
            unsigned megsOfMemory; 
            string deviceIniFilename;
            string systemIniFilename;
            unsigned tpTurnLength;
            bool genTrace;
            string traceFilename;
            string pwd;
            string *visFilename;
            string outputFilename;
            ClockDomain::ClockDomainCrosser clockDomainCrosser; 
            static void mkdirIfNotExist(string path);
            static bool fileExists(string path); 
            CSVWriter *csvOut; 
    };
}
