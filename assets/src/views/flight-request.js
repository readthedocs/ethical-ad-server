const ko = require('knockout');


function FlightRequestViewModel(method) {
  this.budget = ko.observable($("#id_budget").val());
  this.regions = ko.observable([...document.querySelectorAll("form [name='regions']:checked")].map(function (node) { return node.value }));
  this.topics = ko.observable([...document.querySelectorAll("form [name='topics']:checked")].map(function (node) { return node.value }));

  this.pricing = JSON.parse($('#data-pricing').text());

  this.estimatedCpm = function () {
    let budget = Math.round(this.budget(), 10);
    let cpm = 0;
    let prices = [];

    let regions = this.regions();
    let topics = this.topics();
    let pricing = this.pricing;

    // Add all the price combinations to an array
    // We will average this array
    regions.forEach(function (region) {
      let region_pricing = pricing[region];
      if (region_pricing) {

        if (topics.length > 0) {
          topics.forEach(function (topic) {
            if (region_pricing[topic]) {
              prices.push(region_pricing[topic]);
            } else {
              // Unknown price for this topic
            }
          });
        } else if (region_pricing["all-developers"]) {
          prices.push(region_pricing["all-developers"]);
        }
      } else {
        // Unknown price for this region
      }
    });

    if (prices.length > 0) {
      let total = prices.reduce(function (a, b) { return a + b});
      cpm = total / prices.length;
    }

    // Apply discounts
    if (budget >= 24990) {
      cpm *= 0.85
    } else if (budget >= 2990) {
      cpm *= 0.9
    }

    return cpm > 0 ? '$' + cpm.toFixed(2) : "TBD";
  }
}


if (document.querySelectorAll("#flight-request-form").length > 0) {
  ko.applyBindings(new FlightRequestViewModel());
}
