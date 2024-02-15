FROM node:16

WORKDIR /app

COPY package.json /app
COPY package-lock.json /app

RUN npm install

COPY ./docker-compose/frontend/entrypoint /entrypoint
RUN chmod +x /entrypoint

ENTRYPOINT [ "/entrypoint" ]
