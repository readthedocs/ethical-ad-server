import * as jquery from 'jquery';
const ko = require('knockout');


function DashboardHomeViewModel(method) {
  this.dashboardFilter = ko.observable();

  // Determines whether a specific advertiser/publisher slug should be visible
  this.shouldShow = function (slug) {
    let filterValue = this.dashboardFilter();
    if (!filterValue) return true;

    filterValue = filterValue.toLowerCase();
    if (slug.search(filterValue) >= 0) return true;

    return false;
  }
}

if ($('#publisher-advertiser-filter').length > 0) {
  ko.applyBindings(new DashboardHomeViewModel());
}
