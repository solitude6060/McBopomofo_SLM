// Copyright (c) 2026 McBopomofo SLM Authors
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

#import "ContextualRerankerDiagnostics.h"

namespace {

struct Counters {
    uint64_t disabledPath = 0;
    uint64_t attempts = 0;
    uint64_t appliedCorrections = 0;
    uint64_t latencyUnder2ms = 0;
    uint64_t latency2To20ms = 0;
    uint64_t latency20To100ms = 0;
    uint64_t latencyOver100ms = 0;
};

Counters gCounters;

}  // namespace

@implementation ContextualRerankerDiagnostics

+ (void)recordDisabledPath
{
    @synchronized(self) {
        ++gCounters.disabledPath;
    }
}

+ (void)recordAttemptWithAppliedCorrection:(BOOL)appliedCorrection elapsedMicroseconds:(uint64_t)elapsedMicroseconds
{
    @synchronized(self) {
        ++gCounters.attempts;
        if (appliedCorrection) {
            ++gCounters.appliedCorrections;
        }

        if (elapsedMicroseconds < 2000) {
            ++gCounters.latencyUnder2ms;
        } else if (elapsedMicroseconds < 20000) {
            ++gCounters.latency2To20ms;
        } else if (elapsedMicroseconds < 100000) {
            ++gCounters.latency20To100ms;
        } else {
            ++gCounters.latencyOver100ms;
        }
    }
}

+ (void)reset
{
    @synchronized(self) {
        gCounters = Counters{};
    }
}

+ (NSString *)diagnosticReport
{
    @synchronized(self) {
        return [NSString stringWithFormat:@"Disabled: %llu, Attempts: %llu, Applied: %llu, Latency <2ms: %llu, 2-20ms: %llu, 20-100ms: %llu, >100ms: %llu",
                                          (unsigned long long)gCounters.disabledPath,
                                          (unsigned long long)gCounters.attempts,
                                          (unsigned long long)gCounters.appliedCorrections,
                                          (unsigned long long)gCounters.latencyUnder2ms,
                                          (unsigned long long)gCounters.latency2To20ms,
                                          (unsigned long long)gCounters.latency20To100ms,
                                          (unsigned long long)gCounters.latencyOver100ms];
    }
}

@end
