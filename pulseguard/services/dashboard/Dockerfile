FROM node:22-alpine AS build
WORKDIR /app
COPY services/dashboard/package.json services/dashboard/package-lock.json ./
# Optional build secret for build machines behind a TLS-intercepting proxy
# (docker-compose.ca.yml); normal builds skip it.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund
COPY services/dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY services/dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
