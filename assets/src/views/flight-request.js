const ko = require('knockout');
import { getFlightPrice, getDiscount } from "../libs/flight-utils";


function FlightRequestViewModel(method) {
  this.budget = ko.observable($("#id_budget").val());
  this.regions = ko.observable([...document.querySelectorAll("form [name='regions']:checked")].map(function (node) { return node.value }));
  this.topics = ko.observable([...document.querySelectorAll("form [name='topics']:checked")].map(function (node) { return node.value }));

  this.estimatedCpm = function () {
    let budget = Math.round(this.budget(), 10);

    let regions = this.regions();
    let topics = this.topics();

    let rateMultiplier = 1.0 - getDiscount(budget);
    let cpm = rateMultiplier * getFlightPrice(regions, topics);

    return cpm > 0 ? '$' + cpm.toFixed(2) : "TBD";
  };
}


if (document.querySelectorAll("#flight-request-form").length > 0) {
  ko.applyBindings(new FlightRequestViewModel());
}
