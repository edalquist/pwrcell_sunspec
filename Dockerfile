ARG BUILD_FROM
FROM ${BUILD_FROM}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apk add --no-cache \
    openssh-client \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo \
    rust \
    bash \
    jq

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/
COPY rootfs/ /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
