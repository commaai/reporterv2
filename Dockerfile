FROM commaregistry.azurecr.io/python3.12-base:latest

ARG SLURM_VERSION=25.11.2-1
ARG SLURM_RELEASE=25.11.2-1%2Bgpu

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
	  bash-completion \
	  ca-certificates \
	  curl \
	  libdbus-1-dev \
	  libb64-0d \
	  libjwt2 \
	  librdkafka1 \
	  libfreeipmi17 \
	  libipmimonitoring6 \
	  libhdf5-dev \
	  liblua5.3-dev \
	  libhwloc-dev \
	  libyaml-dev \
	&& apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update \
  && curl -L -o slurm-smd_${SLURM_VERSION}_amd64.deb "https://github.com/commaai/slurm-builder/releases/download/${SLURM_RELEASE}/slurm-smd_${SLURM_VERSION}_amd64.deb" \
	&& curl -L -o slurm-smd-client_${SLURM_VERSION}_amd64.deb "https://github.com/commaai/slurm-builder/releases/download/${SLURM_RELEASE}/slurm-smd-client_${SLURM_VERSION}_amd64.deb" \
	&& dpkg -i slurm-smd_${SLURM_VERSION}_amd64.deb slurm-smd-client_${SLURM_VERSION}_amd64.deb || apt-get install -f -y \
	&& rm slurm-smd_${SLURM_VERSION}_amd64.deb slurm-smd-client_${SLURM_VERSION}_amd64.deb \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN id -u batman >/dev/null 2>&1 || useradd --create-home --shell /bin/bash batman

WORKDIR /app

COPY pyproject.toml uv.lock README.md start.sh ./
COPY reporterv2 reporterv2

RUN chmod +x start.sh
RUN uv sync --frozen

ENV REPORTERV2_HOST=/tmp/reporterv2-store
ENV REPORTERV2_DATA=/tmp/reporterv2-index

EXPOSE 8802

CMD ["./start.sh"]
