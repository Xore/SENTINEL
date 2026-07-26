FROM golang:1.26-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/api ./cmd/api

FROM alpine:3.22

RUN apk add --no-cache ca-certificates \
    && addgroup -S sentinel \
    && adduser -S -G sentinel sentinel
COPY --from=build /out/api /usr/local/bin/sentinel-api

USER sentinel
EXPOSE 8080
CMD ["sentinel-api"]
