const ko = require('knockout');
import { getFlightPrice, getDiscount } from "../libs/flight-utils";


function FlightUpdateViewModel(method) {
  this.budget = ko.observable($("#id_budget").val());
  this.cpm = ko.observable($("#id_cpm").val());
  this.cpc = ko.observable($("#id_cpc").val());
  this.sold_impressions = ko.observable($("#id_sold_impressions").val());
  this.sold_clicks = ko.observable($("#id_sold_clicks").val());

  this.regions = ko.observable([...document.querySelectorAll("form [name='include_regions']:checked")].map(function (node) { return node.value }));
  this.topics = ko.observable([...document.querySelectorAll("form [name='include_topics']:checked")].map(function (node) { return node.value }));


  this.updateBudget = function () {
    let budget = Math.round(this.budget(), 10);

    if (Number(this.cpm()) > 0) {
      this.cpc(0);
      this.sold_clicks(0);
      this.sold_impressions(parseInt(1000 * budget / Number(this.cpm())));
    }
    if (Number(this.cpc()) > 0) {
      this.cpm(0);
      this.sold_impressions(0);
      this.sold_clicks(parseInt(budget / Number(this.cpc())));
    }
  }

  this.estimatedCpm = function () {
    let budget = Math.round(this.budget(), 10);

    let regions = this.regions();
    let topics = this.topics();

    let rateMultiplier = 1.0 - getDiscount(budget);
    let cpm = rateMultiplier * getFlightPrice(regions, topics);

    return cpm > 0 ? '$' + cpm.toFixed(2) : "TBD";
  };

  this.budget.subscribe(function () {
    this.updateBudget();
  }, this);
  this.cpm.subscribe(function () {
    this.updateBudget();
  }, this);
  this.cpc.subscribe(function () {
    this.updateBudget();
  }, this);
}


if (document.querySelectorAll("#flight-renew-form").length > 0 || document.querySelectorAll("#flight-update-form").length > 0) {
  ko.applyBindings(new FlightUpdateViewModel());
}
