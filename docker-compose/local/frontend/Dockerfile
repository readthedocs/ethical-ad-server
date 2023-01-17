FROM node:14

WORKDIR /app

COPY package.json /app
COPY package-lock.json /app

RUN npm install

COPY ./docker-compose/local/frontend/entrypoint /entrypoint
RUN chmod +x /entrypoint

ENTRYPOINT [ "/entrypoint" ]
