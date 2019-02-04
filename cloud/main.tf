# Ethical Ads Terraform configuration

# Credentials are in env vars
provider "azurerm" {
    version = "=1.21.0"
    subscription_id = "8252d4f2-f519-485f-80e3-1a051e8c1af4"
}

resource "azurerm_resource_group" "ethicaladserver" {
    name = "EthicalAdServer"
    location = "East US"

    lifecycle {
        prevent_destroy = true
    }
}

resource "azurerm_redis_cache" "ethicaladsredis" {
  name     = "ethicaladsredis"
  resource_group_name = "EthicalAdServer"
  location = "East US"
  capacity = "0"
  family = "C"
  sku_name = "Basic",

  redis_configuration {
    maxmemory_reserved = 2
    maxmemory_delta    = 2
    maxmemory_policy   = "allkeys-lru"
  }

}

resource "azurerm_app_service_plan" "EthicalAdPlan" {
  name                = "EthicalAdPlan"
  location            = "US East"
  resource_group_name = "EthicalAdServer"
  kind = "Linux"

  sku {
      tier = "Standard"
      size = "S1"
  }

}

resource "azurerm_app_service" "ethicalads" {
  name                = "ethicaladserver"
  location = "East US"
  resource_group_name = "EthicalAdServer"
  app_service_plan_id = "${azurerm_app_service_plan.EthicalAdPlan.id}"
}


resource "azurerm_postgresql_server" "ethicaladdb" {
  name                = "ethicaladdb"
  location            = "US East"
  resource_group_name = "EthicalAdServer"

  sku {
    name     = "B_Gen5_1"
    capacity = 1
    tier     = "Basic"
    family   = "Gen5"
  }


  storage_profile {
    storage_mb            = 5120
    backup_retention_days = 7
    geo_redundant_backup  = "Disabled"
  }

  administrator_login          = "ethicaladuser"
  administrator_login_password = "docsrocks"
  version                      = "10.0"
  ssl_enforcement              = "Enabled"

}
