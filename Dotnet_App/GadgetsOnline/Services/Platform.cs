using System;
using System.Collections.Concurrent;
using System.Net.Http;
using System.Runtime.InteropServices;

namespace GadgetsOnline.Services
{
    /// <summary>
    /// Facts about the machine this instance is running on, for the on-screen
    /// readout that identifies which processor produced a benchmark result.
    ///
    /// Values are read once and cached: instance metadata cannot change for the
    /// life of a process, and the benchmark must not be perturbed by an HTTP call
    /// to the metadata service while it is running.
    /// </summary>
    public static class Platform
    {
        private const string MetadataBase = "http://169.254.169.254/latest";

        // Deliberately short. Off EC2 -- a laptop, a local container -- this
        // address is unroutable and the request must fail fast rather than stall
        // the first page load.
        private static readonly TimeSpan MetadataTimeout = TimeSpan.FromSeconds(2);

        private static readonly ConcurrentDictionary<string, string> Cache = new ConcurrentDictionary<string, string>();

        /// <summary>Processor architecture of this process. Always available, no
        /// network call, so it works identically on EC2 and on a laptop.</summary>
        public static string Architecture => RuntimeInformation.OSArchitecture.ToString();

        public static string InstanceType => GetMetadata("meta-data/instance-type");

        public static string InstanceId => GetMetadata("meta-data/instance-id");

        /// <summary>
        /// Total memory the machine reports, formatted for display.
        ///
        /// Read from /proc/meminfo rather than GC.GetGCMemoryInfo, which reports the
        /// limit the runtime may use -- inside a container that is the cgroup limit,
        /// not the instance specification this demo is comparing.
        /// </summary>
        public static string Memory => Cache.GetOrAdd("__memory", _ => ReadTotalMemory());

        private static string ReadTotalMemory()
        {
            try
            {
                foreach (var line in System.IO.File.ReadLines("/proc/meminfo"))
                {
                    if (!line.StartsWith("MemTotal:", StringComparison.Ordinal))
                    {
                        continue;
                    }

                    // "MemTotal:       16093712 kB"
                    var parts = line.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                    if (parts.Length >= 2 && long.TryParse(parts[1], out var kb))
                    {
                        // Rounded to the nearest GiB. EC2 reports slightly under the
                        // advertised figure once firmware reservations are deducted,
                        // and "7.7 GiB" beside a "c7g.xlarge" label only invites
                        // questions during a demo.
                        return $"{Math.Round(kb / 1024.0 / 1024.0):0} GiB";
                    }
                }
            }
            catch (Exception)
            {
                // Not Linux, or /proc is unavailable.
            }

            return "Unavailable";
        }

        public static string Hostname => GetMetadata("meta-data/hostname");

        public static string AvailabilityZone => GetMetadata("meta-data/placement/availability-zone");

        /// <summary>
        /// Reads an instance metadata path using IMDSv2. Returns "Unavailable" off
        /// EC2 or on any failure -- the demo page must render regardless.
        /// </summary>
        private static string GetMetadata(string path)
        {
            return Cache.GetOrAdd(path, FetchMetadata);
        }

        private static string FetchMetadata(string path)
        {
            try
            {
                using var client = new HttpClient { Timeout = MetadataTimeout };

                var tokenRequest = new HttpRequestMessage(HttpMethod.Put, $"{MetadataBase}/api/token");
                tokenRequest.Headers.Add("X-aws-ec2-metadata-token-ttl-seconds", "21600");

                var tokenResponse = client.Send(tokenRequest);
                if (!tokenResponse.IsSuccessStatusCode)
                {
                    return "Unavailable";
                }

                var token = tokenResponse.Content.ReadAsStringAsync().GetAwaiter().GetResult();

                var request = new HttpRequestMessage(HttpMethod.Get, $"{MetadataBase}/{path}");
                request.Headers.Add("X-aws-ec2-metadata-token", token);

                var response = client.Send(request);
                if (!response.IsSuccessStatusCode)
                {
                    return "Unavailable";
                }

                return response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            }
            catch (Exception)
            {
                // Not on EC2, metadata disabled, or the hop limit blocked us. The
                // architecture readout above still works, which is what the demo
                // actually depends on.
                return "Unavailable";
            }
        }
    }
}
