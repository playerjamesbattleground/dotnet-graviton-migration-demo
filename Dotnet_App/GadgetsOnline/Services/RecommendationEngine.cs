using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;

namespace GadgetsOnline.Services
{
    /// <summary>
    /// Scores synthetic product candidates to saturate every available core for a
    /// fixed wall-clock window, then reports the throughput achieved.
    ///
    /// Fixed duration rather than fixed work is deliberate: a live demo needs a
    /// predictable run length, and throughput (operations per second) reads like a
    /// frame rate -- higher is plainly better -- where a completion time does not.
    ///
    /// Registered as a singleton because a run's progress must outlive the request
    /// that started it, so the browser can poll for it.
    /// </summary>
    public class RecommendationEngine
    {
        /// <summary>Candidate pool size. Small enough to stay in cache, so the run
        /// measures compute rather than memory bandwidth.</summary>
        private const int CandidateCount = 512;

        /// <summary>Scoring passes between shared-counter updates. Batching keeps
        /// the interlocked write off the hot path, where it would otherwise
        /// dominate the measurement on higher core counts.</summary>
        private const int CounterBatch = 256;

        private const int MinDurationSeconds = 3;
        private const int MaxDurationSeconds = 30;

        // 0 = idle or finished, 1 = running. Guards against a double-click
        // starting a second run that would corrupt the first one's numbers.
        private int _running;

        private long _operations;
        private long _startedAtTicks;
        private int _durationSeconds;

        private volatile RunResult _lastResult;

        public int ThreadCount => Environment.ProcessorCount;

        public bool IsRunning => Volatile.Read(ref _running) == 1;

        /// <summary>
        /// Starts a run if none is in progress. Returns false when one already is,
        /// leaving the in-flight run untouched.
        /// </summary>
        public bool TryStart(int durationSeconds)
        {
            if (durationSeconds < MinDurationSeconds) durationSeconds = MinDurationSeconds;
            if (durationSeconds > MaxDurationSeconds) durationSeconds = MaxDurationSeconds;

            if (Interlocked.CompareExchange(ref _running, 1, 0) != 0)
            {
                return false;
            }

            Interlocked.Exchange(ref _operations, 0);
            _durationSeconds = durationSeconds;
            Interlocked.Exchange(ref _startedAtTicks, Stopwatch.GetTimestamp());

            // Long-running work on dedicated threads rather than the thread pool,
            // so saturating every core cannot starve the pool that is still serving
            // the status-poll requests driving the on-screen readout.
            var deadline = TimeSpan.FromSeconds(durationSeconds);
            Task.Factory.StartNew(
                () => RunToCompletion(deadline),
                CancellationToken.None,
                TaskCreationOptions.LongRunning,
                TaskScheduler.Default);

            return true;
        }

        private void RunToCompletion(TimeSpan duration)
        {
            var stopwatch = Stopwatch.StartNew();
            var threads = new List<Thread>(ThreadCount);

            try
            {
                for (var i = 0; i < ThreadCount; i++)
                {
                    var seed = i;
                    var thread = new Thread(() => ScoreUntil(stopwatch, duration, seed))
                    {
                        IsBackground = true,
                        Name = $"recommendation-worker-{seed}",
                    };
                    threads.Add(thread);
                    thread.Start();
                }

                foreach (var thread in threads)
                {
                    thread.Join();
                }

                stopwatch.Stop();

                var operations = Interlocked.Read(ref _operations);
                var seconds = stopwatch.Elapsed.TotalSeconds;

                _lastResult = new RunResult
                {
                    Operations = operations,
                    ElapsedSeconds = Math.Round(seconds, 2),
                    OperationsPerSecond = seconds > 0 ? (long)(operations / seconds) : 0,
                    Threads = ThreadCount,
                    Architecture = Platform.Architecture,
                    InstanceType = Platform.InstanceType,
                    CompletedAtUtc = DateTime.UtcNow,
                };
            }
            finally
            {
                // Released even on failure, so a faulted run cannot wedge the
                // engine into a permanently "running" state for the rest of the demo.
                Interlocked.Exchange(ref _running, 0);
            }
        }

        /// <summary>
        /// The measured workload. Mixed floating point, branching, a sort and a
        /// periodic hash -- shaped like real recommendation scoring rather than a
        /// single instruction class, so the result is not an artefact of one
        /// processor extension.
        /// </summary>
        private void ScoreUntil(Stopwatch stopwatch, TimeSpan duration, int seed)
        {
            // Per-thread buffers, allocated once, so the run measures compute and
            // not the garbage collector.
            var scores = new double[CandidateCount];
            var affinity = new double[CandidateCount];
            var hashInput = new byte[64];
            using var sha = SHA256.Create();

            var random = new Random(seed * 7919 + 13);
            for (var i = 0; i < CandidateCount; i++)
            {
                affinity[i] = random.NextDouble();
            }

            long localOperations = 0;
            long batch = 0;
            var pass = 0;

            while (stopwatch.Elapsed < duration)
            {
                // 1. Score every candidate: transcendental maths plus a branch.
                for (var i = 0; i < CandidateCount; i++)
                {
                    var weight = affinity[i];
                    var recency = (pass + i) % 97 / 97.0;
                    var score = Math.Sqrt(weight * 4.0 + 1.0)
                                + Math.Log(1.0 + recency * 3.0)
                                - weight * recency;

                    if (score > 1.5)
                    {
                        score *= 1.0 + weight * 0.25;
                    }

                    scores[i] = score;
                }

                // 2. Rank them. Comparison-heavy, cache-friendly, unavoidable in
                //    any real recommendation path.
                Array.Sort(scores);

                // 3. Derive a cache key for the ranked list. Kept to one hash per
                //    pass so cryptographic acceleration cannot dominate the result.
                BitConverter.TryWriteBytes(hashInput.AsSpan(0, 8), scores[CandidateCount - 1]);
                BitConverter.TryWriteBytes(hashInput.AsSpan(8, 8), scores[0]);
                BitConverter.TryWriteBytes(hashInput.AsSpan(16, 4), pass);
                sha.ComputeHash(hashInput);

                localOperations++;
                batch++;
                pass++;

                if (batch >= CounterBatch)
                {
                    Interlocked.Add(ref _operations, batch);
                    batch = 0;
                }
            }

            if (batch > 0)
            {
                Interlocked.Add(ref _operations, batch);
            }

            // Keeps the loop above from being optimised away entirely.
            if (localOperations < 0)
            {
                throw new InvalidOperationException("unreachable");
            }
        }

        /// <summary>Live snapshot for the on-screen readout.</summary>
        public StatusSnapshot GetStatus()
        {
            var running = IsRunning;
            var operations = Interlocked.Read(ref _operations);

            double elapsedSeconds = 0;
            var startedAt = Interlocked.Read(ref _startedAtTicks);
            if (startedAt > 0)
            {
                elapsedSeconds = (Stopwatch.GetTimestamp() - startedAt) / (double)Stopwatch.Frequency;
            }

            var duration = _durationSeconds;
            if (running && duration > 0 && elapsedSeconds > duration)
            {
                // Workers check the deadline between passes, so elapsed can drift a
                // little past it. Clamping keeps the progress bar from overshooting.
                elapsedSeconds = duration;
            }

            return new StatusSnapshot
            {
                Running = running,
                Operations = operations,
                ElapsedSeconds = Math.Round(elapsedSeconds, 1),
                DurationSeconds = duration,
                PercentComplete = duration > 0
                    ? (int)Math.Min(100, elapsedSeconds / duration * 100)
                    : 0,
                OperationsPerSecond = elapsedSeconds > 0.2
                    ? (long)(operations / elapsedSeconds)
                    : 0,
                Threads = ThreadCount,
                Architecture = Platform.Architecture,
                InstanceType = Platform.InstanceType,
                InstanceId = Platform.InstanceId,
                Memory = Platform.Memory,
                LastResult = _lastResult,
            };
        }

        public class StatusSnapshot
        {
            public bool Running { get; set; }
            public long Operations { get; set; }
            public double ElapsedSeconds { get; set; }
            public int DurationSeconds { get; set; }
            public int PercentComplete { get; set; }
            public long OperationsPerSecond { get; set; }
            public int Threads { get; set; }
            public string Architecture { get; set; }
            public string InstanceType { get; set; }
            public string InstanceId { get; set; }
            public string Memory { get; set; }
            public RunResult LastResult { get; set; }
        }

        public class RunResult
        {
            public long Operations { get; set; }
            public double ElapsedSeconds { get; set; }
            public long OperationsPerSecond { get; set; }
            public int Threads { get; set; }
            public string Architecture { get; set; }
            public string InstanceType { get; set; }
            public DateTime CompletedAtUtc { get; set; }
        }
    }
}
