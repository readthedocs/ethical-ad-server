.PHONY: help test clean dockerbuild dockerserve dockershell geoip

GEOIP_DIR = geoip
GEOIP_CONF_FILE = config/GeoIP.conf

DOCKER_CONFIG=docker-compose-local.yml

help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  test           Run the full test suite"
	@echo "  clean          Delete assets processed by webpack"
	@echo "  dockerbuild    Build the multi-container ad server (this can take a while)"
	@echo "  dockerserve    Run the docker containers for the ad server"
	@echo "  dockershell    Connect to a shell on the Django docker container"
	@echo "  geoip          Download the GeoIP database from MaxMind"

test:
	tox

clean:
	rm -rf assets/dist/*

# Build the local multi-container application
# This command can take a while the first time
dockerbuild: clean geoip
	docker-compose -f $(DOCKER_CONFIG) build

# You should run "dockerbuild" at least once before running this
# It isn't a dependency because running "dockerbuild" can take some time
dockerserve:
	docker-compose -f $(DOCKER_CONFIG) up

# Use this command to inspect the container, run management commands,
# or run anything else on the Django container
dockershell:
	docker-compose -f $(DOCKER_CONFIG) run --rm django /bin/ash

# Get the GeoIP database from MaxMind
# This command will probably fail unless you have "geoipupdate" installed
geoip:
	-geoipupdate -f $(GEOIP_CONF_FILE) -d $(GEOIP_DIR)
