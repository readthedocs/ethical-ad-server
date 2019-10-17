FROM node:12

WORKDIR /app

COPY package.json /app

RUN npm install && rm -f package.json

ENTRYPOINT [ "npm", "run", "watch" ]
