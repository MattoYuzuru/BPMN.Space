# SSH-мост к HTTP-прокси на другом сервере (профиль `egress` в compose.yaml).
FROM alpine:3.22
RUN apk add --no-cache openssh-client \
  && adduser -D -H -u 10110 egress
COPY relay.sh /usr/local/bin/relay.sh
USER egress
EXPOSE 3128
ENTRYPOINT ["/bin/sh", "/usr/local/bin/relay.sh"]
