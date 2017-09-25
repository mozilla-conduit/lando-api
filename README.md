# Lando API

A microservice that turns Phabricator revisions into Mercurial commits.

Part of Mozilla [Conduit](https://wiki.mozilla.org/EngineeringProductivity/Projects/Conduit), 
our code management microservice ecosystem.

## Building the service

##### Prerequisites

 * `docker` (on OS X you will want `docker-machine`, too)
 * `docker-compose`
 * `pyinvoke` (v0.13+, can be installed on OS X with a [Homebrew formula](http://brewformulas.org/pyinvoke))

##### Running the development server

To create a database:

```bash
$ invoke upgrade
```

To build and start the development services' containers: 

```bash
$ docker-compose up 
```

##### Accessing the development server

You need to tell docker-compose to map the webservice's exposed port to a port
on your docker host system.  Create a file named [docker-compose.override.yml](https://docs.docker.com/compose/extends/) 
in the project root with these contents:

```yaml
version: '2'
services:
  lando-api:
    ports:
      - 8000:80
```

Now run `docker-compose up` in the project root.

You can use a tool like [httpie](http://httpie.org/) to test the service.

```yaml
$ http localhost:8000
HTTP/1.0 302 FOUND
Content-Length: 0
Content-Type: application/json
Date: Fri, 28 Apr 2017 00:03:10 GMT
Location: http://localhost:8000/ui/
Server: Werkzeug/0.12.1 Python/3.5.3 
```

## Browsing the API documentation

Start a development server and expose its ports as documented above, and visit 
`http://localhost:8000/ui/` in your browser to view the API documentation.

## Testing

We're using `pytest` with `pytest-flask`. All tests are placed in `./tests/`
To run the tests please call

```bash
$ invoke test
```

