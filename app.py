from oophelpers import *
from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit, join_room, disconnect, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, session, request, redirect, url_for, jsonify
import sqlite3
from random import randint

app = Flask(__name__, static_folder='static')

# app = Flask(__name__)
app.config['SECRET_KEY'] = 'top-secret!'
app.config['SESSION_TYPE'] = 'filesystem'

socketio = SocketIO(app)

# Initialize the database (create the users table if not exists)
def initialize_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    ''')
    conn.commit()
    conn.close()

# Connect to SQLite database
def get_db_connection():
    conn = sqlite3.connect('users.db')
    conn.row_factory = sqlite3.Row
    return conn


# Initialize the database
initialize_db()





# Function to add a new user to the database
def add_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed_password = generate_password_hash(password)
    try:
        cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_password))
        conn.commit()
    except sqlite3.IntegrityError:
        return False  # Username already exists
    finally:
        conn.close()
    return True

# Function to check if a user exists and validate password
def validate_user(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()
    if user and check_password_hash(user['password'], password):
        return True
    return False


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    confirm_password = data.get('confirm_password')

    # Validate passwords
    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match!'}), 400
    
    if add_user(username, password):
      
        return jsonify({'message': 'Registration successful!'}), 201
    else:
        return jsonify({'error': 'Username already exists!'}), 400

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if validate_user(username, password):
        
        return jsonify({'message': 'Login successful!'}), 200
    else:
        return jsonify({'error': 'Invalid username or password!'}), 400

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return jsonify({'message': 'Logged out successfully!'}), 200


@app.route('/')
def index():
    return render_template('login.html')

@app.route('/re')
def re():
    return render_template('register.html')

@app.route('/game')
def game():
    # Get the username from the query parameter
    username = request.args.get('username')
    return render_template('index.html', username=username)

activeGamingRooms = []
connectetToPortalUsers = []

# ! server-client communication

# ################# handler(1') #################
# handler for player/client connect event
# emited events: tooManyPlayers(msg) OR clientId(msg),connected-Players(msg), status(msg)
@socketio.event
def connect():
    """

    """
    global connectetToPortalUsers
    player = Player(request.sid)
    connectetToPortalUsers.append(player)
    
    emit('connection-established', 'go', to=request.sid)


@socketio.on('check-game-room')
def checkGameRoom(data):
    global onlineClients
    global connectetToPortalUsers
    global activeGamingRooms
    # user index
    userIdx = getPlayerIdx(connectetToPortalUsers, request.sid)
    if userIdx is not None:
        connectetToPortalUsers[userIdx].name = data['username']
        connectetToPortalUsers[userIdx].requestedGameRoom = data['room']
    
    # check if room exists in activeGamingRooms
    roomIdx = getRoomIdx(activeGamingRooms, data['room'])
    # if room not existing
    if roomIdx is None:
        room = GameRoom(data['room'])
        room.add_player(connectetToPortalUsers[userIdx])
        activeGamingRooms.append(room)
        
        # join socketIO gameroom
        join_room( data['room'])
        emit('tooManyPlayers', 'go', to=request.sid)

    else:
        if activeGamingRooms[roomIdx].roomAvailable():
            activeGamingRooms[roomIdx].add_player(connectetToPortalUsers[userIdx])
            
            join_room( data['room'])
            emit('tooManyPlayers', 'go', to=request.sid)
        else:
            # print local to server console
            print('Too many players tried to join!')
            # send to client
            
            emit('tooManyPlayers', 'tooCrowdy', to=request.sid)
            disconnect()
            return
    
    session['username'] = data['username']
    session['room'] = data['room']


# ####### Server asyn
@socketio.event
def readyToStart():
    global activeGamingRooms
    
    roomIdx = getRoomIdx(activeGamingRooms, session['room'])
    playerId = activeGamingRooms[roomIdx].getPlayerIdx(request.sid)
    onlineClients = activeGamingRooms[roomIdx].getClientsInRoom('byName')
    
    emit('clientId', (playerId, session.get('room')))
    emit('connected-Players', [onlineClients], to=session['room'])
    emit('status', {'clientsNbs': len(onlineClients), 'clientId': request.sid}, to=session['room'])

# #######

# ! CHAT BETWEEN PLAYERS
# Event handler for player/client message
# ################# handler(1c) #################
# emited events: player message(msg)
@socketio.event
def my_broadcast_event(message):
    emit('player message',
         {'data': message['data'], 'sender':message['sender']}, to=session['room'])

# ! CHAT BETWEEN PLAYERS

# ################# handler(2) #################
# start the game when 2 players pressed the Start (or Restart) button
# emited events: start(msg) OR <waiting second player start>
@socketio.event
def startGame(message):
    global activeGamingRooms
    global connectetToPortalUsers
    userIdx = getPlayerIdx(connectetToPortalUsers, request.sid)
    roomIdx = getRoomIdx(activeGamingRooms, session['room'])

    connectetToPortalUsers[userIdx].start_game_intention()
    started = activeGamingRooms[roomIdx].get_ready_for_game()

    activePlayer = activeGamingRooms[roomIdx].get_rand_active_player()
    if (started):
        emit('start', {'activePlayer':activePlayer, 'started': started}, to=session['room'])
    else:
        emit('waiting second player start', to=session['room'])

# ################# handler(3) #################
# start the game when 2 players pressed the Start button
# emited events: turn(msg)
@socketio.on('turn')
def turn(data):
    global activeGamingRooms
    roomIdx = getRoomIdx(activeGamingRooms, session['room'])

    activePlayer = activeGamingRooms[roomIdx].get_swap_player()


    # global activePlayer
    print('turn by {}: position {}'.format(data['player'], data['pos']))
      
    # ! TODO set the fields
    # notify all clients that turn happend and over the next active id
    emit('turn', {'recentPlayer':data['player'], 'lastPos': data['pos'], 'next':activePlayer}, to=session['room'])

# ################# handler(3.1) #################
# information about game status
@socketio.on('game_status')
def game_status(msg):
    
    # get status for restart game
    global activeGamingRooms
    roomIdx = getRoomIdx(activeGamingRooms, session['room'])
    activeGamingRooms[roomIdx].startRound()
    
    print(msg['status'])


# get key by value from a dict
def getKeybyValue(obj, value):
    key = [k for k, v in obj.items() if v == value]
    return key

# get player's index from all players list
def getPlayerIdx(obj, sid):
    idx = 0
    for player in obj:
        if player.id == sid:
            return idx
        idx +=1

# get room's index from active rooms list
def getRoomIdx(obj, roomName):
    idx = 0
    for player in obj:
        if player.name == roomName:
            return idx
        idx +=1

@socketio.event
def disconnect():
    global activeGamingRooms
    global connectetToPortalUsers
    userIdx = getPlayerIdx(connectetToPortalUsers, request.sid)             # user position in connectedToPortalUsers
    
    if session.get('room') is not None:
    
        roomIdx = getRoomIdx(activeGamingRooms, session['room'])                # active room of the user
        userIdxInRoom = activeGamingRooms[roomIdx].getPlayerIdx(request.sid)    # user index in active room
        
        del activeGamingRooms[roomIdx].onlineClients[userIdxInRoom]             # delete the user from active room
        del connectetToPortalUsers[userIdx]                                     # delete user from connectedToPortalUsers

        onlineClients = activeGamingRooms[roomIdx].get_players_nbr()
        print("client with sid: {} disconnected".format(request.sid))

        if onlineClients == 0:
            roomName = activeGamingRooms[roomIdx].name
            del activeGamingRooms[roomIdx]
            print ('room: {} closed'.format(roomName))
        else:
            # emit('status', {'clients': onlineClients}, to=session['room'])
            emit('disconnect-status', {'clientsNbs': onlineClients, 'clientId': request.sid}, to=session['room'])



if __name__ == '__main__':
    socketio.run(app, debug=True)
