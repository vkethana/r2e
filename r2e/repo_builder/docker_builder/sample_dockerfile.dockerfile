FROM ubuntu
RUN apt-get update

ENV DEBIAN_FRONTEND noninteractive

RUN echo "tzdata tzdata/Areas select America" | debconf-set-selections && echo "tzdata tzdata/Zones/America select Los_Angeles" | debconf-set-selections

# Install standard and python specific system dependencies
RUN apt-get install -y git curl wget build-essential libatlas-base-dev gfortran python3-dev python3-pip python-dev-is-python3 libpq-dev libxml2-dev libxslt1-dev libmysqlclient-dev libtiff5-dev libjpeg8-dev zlib1g-dev libfreetype6-dev liblcms2-dev libwebp-dev libgmp3-dev libcurl4-openssl-dev portaudio19-dev 

# Install Anaconda
RUN wget https://repo.anaconda.com/archive/Anaconda3-2023.09-0-Linux-x86_64.sh && \
    bash Anaconda3-2023.09-0-Linux-x86_64.sh -b -p /opt/anaconda && \
    rm Anaconda3-2023.09-0-Linux-x86_64.sh

# Add Anaconda to PATH
ENV PATH="/opt/anaconda/bin:${PATH}"
