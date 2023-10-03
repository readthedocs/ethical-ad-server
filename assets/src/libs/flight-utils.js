function getFlightPrice(regions, topics) {
  let prices = [];
  let pricing = JSON.parse($('#data-pricing').text());
  let cpm = 0;

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

  return cpm;
};


function getDiscount(budget) {
  if (budget >= 24990) {
    return 0.15;
  } else if (budget >= 2990) {
    return 0.1;
  }

  return 0;
};

export { getFlightPrice, getDiscount };
