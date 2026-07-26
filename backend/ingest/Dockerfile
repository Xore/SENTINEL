FROM golang:1.26-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/ingest ./cmd/ingest \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/migrate ./cmd/migrate

FROM alpine:3.22

RUN apk add --no-cache ca-certificates \
    && addgroup -S sentinel \
    && adduser -S -G sentinel sentinel
COPY --from=build /out/ingest /usr/local/bin/ingest
COPY --from=build /out/migrate /usr/local/bin/migrate

USER sentinel
CMD ["ingest"]
