#!/usr/bin/env python
from gevent import monkey;monkey.patch_all()
from app import app
#from socketio.server import SocketIOServer
from gevent.pywsgi import WSGIServer
try:
    from geventwebsocket import WebSocketHandler
except ImportError:
    from geventwebsocket.handler import WebSocketHandler

#socket_io_server = SocketIOServer( ('', 5000), app, resource='socket.io')
#server = WebSocketServer(('', 5000), app)
server = WSGIServer(('', 5000), app,
                    handler_class=WebSocketHandler)

if __name__ == '__main__':
    print 'Listening on http://localhost:5000/'
    server.serve_forever()
