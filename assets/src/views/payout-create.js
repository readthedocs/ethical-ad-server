const ko = require('knockout');


function PayoutStartViewModel() {
  this.body = ko.observable(document.querySelector("#id_body").value);

  this.displayBody = function () {
    return this.body;
  };
}


if (document.querySelectorAll("#payout-start").length > 0) {
  ko.applyBindings(new PayoutStartViewModel());
}
