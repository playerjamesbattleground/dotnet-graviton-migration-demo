using GadgetsOnline.Services;
using Microsoft.AspNetCore.Mvc;

namespace GadgetsOnline.Controllers
{
    /// <summary>
    /// Drives the personalisation pass that the storefront's "Find My Perfect
    /// Gadget" button triggers, and reports its progress to the on-screen readout.
    /// </summary>
    public class RecommendationsController : Controller
    {
        private readonly RecommendationEngine _engine;

        public RecommendationsController(RecommendationEngine engine)
        {
            _engine = engine;
        }

        /// <summary>
        /// Begins a pass. Returns 409 when one is already running rather than
        /// starting a second, so a double-click cannot corrupt the measurement.
        /// </summary>
        [HttpPost]
        [IgnoreAntiforgeryToken]
        public IActionResult Start(int seconds = 10)
        {
            if (!_engine.TryStart(seconds))
            {
                return Conflict(new { message = "A personalisation pass is already running." });
            }

            return Json(_engine.GetStatus());
        }

        /// <summary>Live snapshot, polled by the storefront while a pass runs.</summary>
        [HttpGet]
        public IActionResult Status()
        {
            // The readout polls several times a second; a cached response would
            // freeze the numbers on screen.
            Response.Headers["Cache-Control"] = "no-store";
            return Json(_engine.GetStatus());
        }
    }
}
