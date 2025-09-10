# app.py — fixed version (eventlet monkey-patch + index public + login_manager rename)

import eventlet
eventlet.monkey_patch()

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.utils import secure_filename
from better_profanity import profanity

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///' + os.path.join(BASE_DIR, 'chat.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# rename LoginManager instance to avoid clobbering by a view named `login`
login_manager = LoginManager(app)
login_manager.login_view = "login"  # when a login-required route is hit, redirect to this endpoint

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)  # use eventlet worker for deployment

profanity.load_censor_words()

# --- Models ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)  # can be nickname
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    gender = db.Column(db.String(10))  # Male / Female / Other
    bio = db.Column(db.Text)
    avatar = db.Column(db.String(300))
    is_admin = db.Column(db.Boolean, default=False)
    banned = db.Column(db.Boolean, default=False)
    muted_until = db.Column(db.DateTime, nullable=True)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    private = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    text = db.Column(db.Text)
    media = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- Login loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Routes ---

# Public landing page — NOT protected (no login required)
@app.route('/')
def index():
    # show a simple landing page; if logged in, show quick link to chat
    rooms = Room.query.order_by(Room.name).all() if current_user.is_authenticated else []
    return render_template('index.html', rooms=rooms)

# Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        name = request.form.get('name', username)
        if User.query.filter_by(username=username).first():
            flash('Username taken', 'danger')
            return redirect(url_for('register'))
        # NOTE: Hash password in production (werkzeug.security.generate_password_hash)
        u = User(username=username, password=password, name=name)
        db.session.add(u)
        db.session.commit()
        login_user(u)
        flash('Welcome! Set up your profile.', 'success')
        return redirect(url_for('profile'))
    return render_template('register.html')

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        pw = request.form['password']
        user = User.query.filter_by(username=username).first()
        # NOTE: Use check_password_hash in production
        if not user or user.password != pw:
            flash('Invalid credentials', 'danger')
            return redirect(url_for('login'))
        if user.banned:
            flash('You are banned', 'danger')
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('chat'))  # send to chat after login
    return render_template('login.html')

# Logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Protected profile route
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name = request.form.get('name', current_user.name)
        current_user.bio = request.form.get('bio', current_user.bio)
        f = request.files.get('avatar')
        if f and f.filename:
            filename = secure_filename(f.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            f.save(path)
            current_user.avatar = 'uploads/' + filename
        db.session.commit()
        flash('Profile updated', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)

# Protected chat landing — requires login
@app.route('/chat')
@login_required
def chat():
    rooms = Room.query.order_by(Room.name).all()
    return render_template('chat_index.html', rooms=rooms)

# Room view — protected
@app.route('/room/<room_name>')
@login_required
def room(room_name):
    room = Room.query.filter_by(name=room_name).first_or_404()
    if room.private and not current_user.is_admin:
        flash('Private room - access denied', 'danger')
        return redirect(url_for('chat'))
    messages = Message.query.filter_by(room_id=room.id).order_by(Message.created_at.asc()).limit(200).all()
    return render_template('chat.html', room=room, messages=messages)

# Create room
@app.route('/create_room', methods=['POST'])
@login_required
def create_room():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Room name required', 'danger')
        return redirect(url_for('chat'))
    if Room.query.filter_by(name=name).first():
        flash('Room exists', 'danger')
        return redirect(url_for('chat'))
    r = Room(name=name, private=bool(request.form.get('private')))
    db.session.add(r)
    db.session.commit()
    flash('Room created', 'success')
    return redirect(url_for('room', room_name=name))

# Serve uploaded files (profile pics / media)
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- Socket.IO handlers ---
@socketio.on('join')
def handle_join(data):
    room_name = data.get('room')
    join_room(room_name)
    emit('system_message', {'msg': f'{current_user.name} joined {room_name}'}, room=room_name)

@socketio.on('leave')
def handle_leave(data):
    room_name = data.get('room')
    leave_room(room_name)
    emit('system_message', {'msg': f'{current_user.name} left {room_name}'}, room=room_name)

@socketio.on('send_message')
def handle_message(data):
    text = (data.get('text') or '').strip()
    room_name = data.get('room')
    if not text and not data.get('media'):
        return
    if current_user.is_anonymous:
        emit('error', {'msg': 'Authentication required.'})
        return
    # moderation checks
    if current_user.banned:
        emit('error', {'msg': 'You are banned.'})
        return
    if current_user.muted_until and current_user.muted_until > datetime.utcnow():
        emit('error', {'msg': 'You are muted.'})
        return
    # censor
    text = profanity.censor(text)
    # store message
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        emit('error', {'msg': 'Room not found.'})
        return
    msg = Message(room_id=room.id, user_id=current_user.id, text=text, media=data.get('media'))
    db.session.add(msg)
    db.session.commit()
    payload = {
        'id': msg.id,
        'user': current_user.name,
        'avatar': current_user.avatar,
        'text': text,
        'media': msg.media,
        'created_at': msg.created_at.isoformat()
    }
    emit('new_message', payload, room=room_name)

# --- Admin actions ---
@app.route('/admin/ban/<int:user_id>')
@login_required
def admin_ban(user_id):
    if not current_user.is_admin:
        abort(403)
    u = User.query.get_or_404(user_id)
    u.banned = True
    db.session.commit()
    flash('User banned', 'info')
    return redirect(url_for('chat'))

@app.route('/admin/unban/<int:user_id>')
@login_required
def admin_unban(user_id):
    if not current_user.is_admin:
        abort(403)
    u = User.query.get_or_404(user_id)
    u.banned = False
    db.session.commit()
    flash('User unbanned', 'info')
    return redirect(url_for('chat'))

@app.route('/admin/mute/<int:user_id>')
@login_required
def admin_mute(user_id):
    if not current_user.is_admin:
        abort(403)
    u = User.query.get_or_404(user_id)
    u.muted_until = datetime.utcnow() + timedelta(minutes=30)
    db.session.commit()
    flash('User muted for 30 minutes', 'info')
    return redirect(url_for('chat'))

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
