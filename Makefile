.PHONY: help test clean dockerbuild dockerserve dockershell

CONTAINER_NAME = ethicaladserver
CONTAINER_ENVS = .envs/production.env

OS = $(shell uname)

ifeq ($(OS), Darwin)
	export LANG = en_US.UTF-8
else
	export LANG = c.UTF-8
endif


help:
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  test           Run the full test suite"
	@echo "  clean          Delete assets processed by webpack"
	@echo "  dockerbuild    Build a docker container of the ad server"
	@echo "  dockerserve    Run the docker container for the ad server on port 5000"
	@echo "  dockershell    Connect to a shell on the docker container"

test:
	tox

clean:
	rm -rf assets/dist/*

dockerbuild: clean
	npm run build-production
	docker build -t $(CONTAINER_NAME) -f deploy/Dockerfile .

dockerserve:
	docker container run --env-file $(CONTAINER_ENVS) --publish 5000:5000 $(CONTAINER_NAME)

dockershell:
	docker container run --env-file $(CONTAINER_ENVS) -it $(CONTAINER_NAME) /bin/bash
