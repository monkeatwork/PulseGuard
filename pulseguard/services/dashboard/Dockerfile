FROM node:20-slim

WORKDIR /srv

COPY services/dashboard/package.json ./package.json
RUN npm install

COPY services/dashboard .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
