FROM golang:1.26 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# modernc.org/sqlite is pure Go, so the binary is fully static.
RUN CGO_ENABLED=0 go build -o /observatory .

FROM gcr.io/distroless/static-debian12
COPY --from=build /observatory /observatory
EXPOSE 8080
ENTRYPOINT ["/observatory"]
