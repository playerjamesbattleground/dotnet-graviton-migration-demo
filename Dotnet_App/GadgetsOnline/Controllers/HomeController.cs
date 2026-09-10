using GadgetsOnline.Services;
using Microsoft.AspNetCore.Mvc;

namespace GadgetsOnline.Controllers
{
    public class HomeController : Controller
    {
        Inventory inventory;

        public ActionResult Index()
        {
            inventory = new Inventory();
            var products = inventory.GetBestSellers(6);

            // Machine identity for the footer readout. Sourced from Platform, which
            // caches instance metadata so a benchmark run is never slowed by a
            // metadata call mid-flight.
            ViewBag.Hostname = "; Node: " + Platform.Hostname;
            ViewBag.AvailabilityZone = "; AZ: " + Platform.AvailabilityZone;
            ViewBag.InstanceType = "; Instance-Type: " + Platform.InstanceType;

            return View(products);
        }

        public ActionResult About()
        {
            ViewBag.Message = "Your application description page.";
            return View();
        }

        public ActionResult Contact()
        {
            ViewBag.Message = "Your contact page.";
            return View();
        }
    }
}
