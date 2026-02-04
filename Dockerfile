# Hello friend!
#
# To build yourself a docker image, you'll want to go into config.yaml first
# and set debug=True. Then (with docker running) run:
#  $ docker build .
# and you'll get a docker image you can start up with:
#  $ docker run -p 5000:5000 -it <RANDOMISH-IMG-ID>
# this will start the container and expose prosecco on your local port 5000
FROM gcr.io/spotify-base-images/trusty-java:0.26

# apt-get install supervisor (to start all the procs), redis, and 
# the more time-consuming python packages
RUN apt-get update && apt-get install -y \
    python \
    python-audioread \
    python-dev \
    python-mock \
    python-msgpack \
    python-nose \
    python-numpy \
    python-pip \
    python-scipy \
    python-setuptools \
    python-sklearn \
    python-support \
    python-unittest2 \
    supervisor\
    redis-server\
    build-essential\
    python-gevent\
    python-markupsafe\
    python-pycryptopp 

# The image runs really old versions of pip and setuptools so we upgrade them
RUN pip install --upgrade pip setuptools

# Add the whole repo to the container and get the rest of the python packages installed
ADD . /prosecco
# Use the internal pip repo
RUN pip install --no-cache-dir -r /prosecco/requirements.txt

ADD supervise/redis.conf /etc/supervisor/conf.d/redis.conf
ADD supervise/player.conf /etc/supervisor/conf.d/player.conf
ADD supervise/main.conf /etc/supervisor/conf.d/main.conf

# This is the port(s) we want to expose
EXPOSE 5000

# Kick off supervisor in interactive mode so the container keeps running
# forever
cmd /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
