using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using GadgetsOnline.Models;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.HttpsPolicy;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

using OpenTelemetry;
using OpenTelemetry.Exporter.OpenTelemetryProtocol;
using OpenTelemetry.Extensions.Hosting;
using OpenTelemetry.Contrib.Extensions.AWSXRay.Trace;
using OpenTelemetry.Instrumentation.AspNetCore;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using OpenTelemetry.Contrib.Instrumentation.AWS;
using Amazon.XRay.Recorder.Core;
using Amazon.XRay.Recorder.Handlers.AwsSdk;
using OpenTelemetry.Instrumentation.Runtime;
using OpenTelemetry.Contrib.Extensions.AWSXRay.Resources;
using OpenTelemetry.Instrumentation.MySqlData;


namespace GadgetsOnline
{
    public class Startup
    {

        public Startup(IConfiguration configuration)
        {
            Configuration = configuration;
            ConfigurationManager.Configuration = configuration;

        }

        public IConfiguration Configuration { get; }

        // This method gets called by the runtime. Use this method to add services to the container.
        public void ConfigureServices(IServiceCollection services)
        {

            if (!String.IsNullOrEmpty(Environment.GetEnvironmentVariable("XRAY")))
            {
                services.AddControllers();
                //var exp_endpoint = Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT");
                // var builder = Sdk.CreateTracerProviderBuilder();

                Sdk.CreateTracerProviderBuilder()
                   .SetResourceBuilder(ResourceBuilder.CreateDefault().AddDetector(new AWSEKSResourceDetector()))
                   .AddXRayTraceId()
                   .AddMySqlDataInstrumentation()
                   .AddSqlClientInstrumentation(options => options.SetDbStatementForText = true)
                   .AddAWSInstrumentation()
                   .AddAspNetCoreInstrumentation()
                   .AddHttpClientInstrumentation()
                   // .AddConsoleExporter()
                   .AddOtlpExporter(options =>
                   {
                       options.Endpoint = new Uri(Environment.GetEnvironmentVariable("OTEL_EXPORTER_OTLP_ENDPOINT"));
                   })
                    .Build();
                Sdk.SetDefaultTextMapPropagator(new AWSXRayPropagator()); // configure AWS X-Ray propagator
            }
            // add support for session-management
            services.AddDistributedMemoryCache();
            services.AddSession(options =>
            {
                options.IdleTimeout = TimeSpan.FromHours(1);
                options.Cookie.HttpOnly = true;
                options.Cookie.IsEssential = true;
            });

            services.AddControllersWithViews();

            // Singleton: a personalisation pass outlives the request that starts
            // it, so its progress must be shared across the polls that follow.
            services.AddSingleton<GadgetsOnline.Services.RecommendationEngine>();

            // ensure data seeding
            using (var context = new GadgetsOnlineEntities())
            {
                context.Database.EnsureCreated();
                context.SaveChanges();
            }
        }

        // This method gets called by the runtime. Use this method to configure the HTTP request pipeline.
        public void Configure(IApplicationBuilder app, IWebHostEnvironment env)
        {
            if (env.IsDevelopment())
            {
                app.UseDeveloperExceptionPage();
            }
            else
            {
                app.UseExceptionHandler("/Home/Error");
                // The default HSTS value is 30 days. You may want to change this for production scenarios, see https://aka.ms/aspnetcore-hsts.
                app.UseHsts();
            }
            // Only redirect when an HTTPS endpoint actually exists. The demo
            // containers serve plain HTTP on :80 with no certificate, where an
            // unconditional redirect would send the browser to a closed port.
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("ASPNETCORE_HTTPS_PORT")))
            {
                app.UseHttpsRedirection();
            }

            app.UseStaticFiles();

            //Added Middleware

            app.UseRouting();

            app.UseAuthorization();

            // add support for session-management 
            app.UseSession();

            app.UseEndpoints(endpoints =>
            {
                endpoints.MapControllerRoute(
                    name: "default",
                    pattern: "{controller=Home}/{action=Index}/{id?}");
            });
        }
    }

    public class ConfigurationManager
    {
        public static IConfiguration Configuration { get; set; }
    }

}
