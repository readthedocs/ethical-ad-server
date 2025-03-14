FROM node:20

WORKDIR /app

COPY package.json /app
COPY package-lock.json /app

RUN npm clean-install

COPY ./docker-compose/frontend/entrypoint /entrypoint
RUN chmod +x /entrypoint

ENTRYPOINT [ "/entrypoint" ]
