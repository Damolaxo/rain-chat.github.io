import os
from datetime import datetime, timedelta

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, join_room, leave_room, emit, send
import bleach

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXT = {'png','jpg','jpeg','gif','mp4','webm','mov'}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///rainchat.db')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB uploads

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'  # if not logged in, redirect here
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

from models import User, Message, Room, Reaction, PinnedMessage, Block, Ban, Mute
from forms import RegisterForm, LoginForm, ProfileForm

# --- Flask-Login user loader ---
@login_manager.user_loader
def load_user(user_id):
    """Tell Flask-Login how to load a user by ID."""
    return User.query.get(int(user_id))

# --- utility functions ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def sanitize(text):
    # basic sanitize using bleach - extend for more rules
    return bleach.clean(text, strip=True)

# --- routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        # check duplicates by email or phone
        if User.query.filter((User.email == form.email.data) | (User.phone == form.phone.data)).first():
            flash("You have registered before. Use login or recover password.", "warning")
            return redirect(url_for('login'))
        u = User(
            name=form.name.data,
            email=form.email.data.lower(),
            nickname=form.nickname.data,
            phone=form.phone.data,
        )
        u.set_password(form.password.data)
        db.session.add(u)
        db.session.commit()
        flash("Successfully registered. You can now login.", "success")
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if not user:
            flash("No account found with that email.", "danger")
            return redirect(url_for('register'))
        if user.check_password(form.password.data):
            # check ban
            ban = Ban.query.filter_by(user_id=user.id).first()
            if ban:
                flash("Your account is banned.", "danger")
                return redirect(url_for('index'))
            login_user(user)
            flash("Successfully logged in.", "success")
            return redirect(url_for('chat'))
        else:
            flash("Invalid credentials.", "danger")
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.nickname = form.nickname.data
        current_user.bio = sanitize(form.bio.data)
        # handle avatar
        f = request.files.get('avatar')
        if f and allowed_file(f.filename):
            filename = secure_filename(f"{current_user.id}-{datetime.utcnow().timestamp()}-{f.filename}")
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            f.save(path)
            current_user.avatar = filename
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for('profile'))
    return render_template('profile.html', form=form)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/chat')
@login_required
def chat():
    rooms = Room.query.filter_by(is_private=False).all()
    return render_template('chat.html', rooms=rooms, user=current_user)

# search messages example
@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    results = []
    if q:
        results = Message.query.filter(Message.content.contains(q)).order_by(Message.timestamp.desc()).limit(100).all()
    return render_template('search.html', results=results, q=q)

# Admin actions: pin message, mute/ban etc (simple POST endpoints)
@app.route('/admin/pin', methods=['POST'])
@login_required
def pin_message():
    if not current_user.is_admin:
        return jsonify({'error': 'forbidden'}), 403
    mid = request.json.get('message_id')
    msg = Message.query.get(mid)
    if not msg:
        return jsonify({'error': 'not found'}), 404
    pm = PinnedMessage(message_id=msg.id, room_id=msg.room_id, pinned_by=current_user.id)
    db.session.add(pm)
    db.session.commit()
    return jsonify({'ok': True})

# --- SocketIO events ---
@socketio.on('join')
def on_join(data):
    room_id = data.get('room')
    room = Room.query.get(room_id)
    if not room:
        emit('error', {'error': 'room not found'})
        return
    # check if user is banned or muted in room
    ban = Ban.query.filter_by(user_id=current_user.id, room_id=room.id).first()
    if ban:
        emit('error', {'error': 'you are banned from this room'})
        return
    join_room(room.room_name)
    emit('status', {'msg': f"{current_user.nickname} has joined."}, room=room.room_name)

@socketio.on('leave')
def on_leave(data):
    room_name = data.get('room_name')
    leave_room(room_name)
    emit('status', {'msg': f"{current_user.nickname} has left."}, room=room_name)

@socketio.on('message')
def on_message(data):
    # data: {room_id, content, reply_to (optional), to_user (optional for private)}
    content = (data.get('content') or '').strip()
    if not content:
        return
    content = sanitize(content)
    # profanity filter
    from utils import contains_profanity
    if contains_profanity(content):
        emit('error', {'error': 'message blocked by profanity filter'})
        return

    room_id = data.get('room_id')
    reply_to = data.get('reply_to')
    to_user = data.get('to_user')  # for private messages

    # check mute
    mute = Mute.query.filter_by(user_id=current_user.id, room_id=room_id).first()
    if mute and mute.expires_at and mute.expires_at > datetime.utcnow():
        emit('error', {'error': 'you are muted'})
        return

    msg = Message(
        user_id=current_user.id,
        room_id=room_id,
        content=content,
        timestamp=datetime.utcnow(),
        reply_to=reply_to,
        is_private=bool(to_user)
    )
    db.session.add(msg)
    db.session.commit()

    payload = {
        'id': msg.id,
        'user': {'id': current_user.id, 'nickname': current_user.nickname, 'avatar': current_user.avatar},
        'content': content,
        'timestamp': msg.timestamp.isoformat(),
        'reply_to': reply_to,
    }
    if to_user:
        # private: emit to both users' personal rooms
        personal_room = f"user_{to_user}"
        my_room = f"user_{current_user.id}"
        emit('private_message', payload, room=personal_room)
        emit('private_message', payload, room=my_room)
    else:
        r = Room.query.get(room_id)
        emit('message', payload, room=r.room_name)

# additional events: reactions, typing, edit, delete (left as TODO)

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
