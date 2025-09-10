import eventlet
eventlet.monkey_patch()

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, join_room, leave_room, emit
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from better_profanity import profanity

from models import db, User, Room, Message
from forms import RegisterForm, LoginForm, ProfileForm, RoomForm

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///' + os.path.join(BASE_DIR, 'chat.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

db.init_app(app)
migrate = Migrate(app, db)

bcrypt = Bcrypt(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

profanity.load_censor_words()


# --- Login loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --- Routes ---
@app.route('/')
def index():
    """Public landing page"""
    rooms = Room.query.order_by(Room.name).all() if current_user.is_authenticated else []
    return render_template('index.html', rooms=rooms)


# Register
@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash("This username is already taken. Please log in.", "warning")
            return redirect(url_for("login"))

        user = User(username=form.username.data, name=form.name.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("You have successfully registered! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form=form)


# Login
@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash("You have successfully logged in!", "success")
            return redirect(url_for("chat"))
        else:
            flash("Invalid username or password.", "danger")
    return render_template("login.html", form=form)


# Logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('login'))


# Profile
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.bio = form.bio.data
        f = form.avatar.data
        if f and f.filename:
            filename = secure_filename(f.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            f.save(path)
            current_user.avatar = 'uploads/' + filename
        db.session.commit()
        flash('Profile updated', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user, form=form)


# Chat landing
@app.route("/chat")
@login_required
def chat():
    return render_template("chat.html", username=current_user.username)


# Room view
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
    form = RoomForm()
    if form.validate_on_submit():
        if Room.query.filter_by(name=form.name.data).first():
            flash('Room already exists.', 'danger')
            return redirect(url_for('chat'))
        r = Room(name=form.name.data, private=form.private.data)
        db.session.add(r)
        db.session.commit()
        flash('Room created successfully!', 'success')
        return redirect(url_for('room', room_name=form.name.data))
    flash('Room creation failed.', 'danger')
    return redirect(url_for('chat'))


# Serve uploaded files
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# --- Socket.IO handlers ---
@socketio.on('join')
def handle_join(data):
    room_name = data.get('room')
    join_room(room_name)
    emit('system_message', {'msg': f'{current_user.username} joined {room_name}'}, room=room_name)


@socketio.on('leave')
def handle_leave(data):
    room_name = data.get('room')
    leave_room(room_name)
    emit('system_message', {'msg': f'{current_user.username} left {room_name}'}, room=room_name)


@socketio.on('send_message')
def handle_message(data):
    text = (data.get('text') or '').strip()
    room_name = data.get('room')
    if not text and not data.get('media'):
        return
    if current_user.is_anonymous:
        emit('error', {'msg': 'Authentication required.'})
        return
    if current_user.banned:
        emit('error', {'msg': 'You are banned.'})
        return
    if current_user.muted_until and current_user.muted_until > datetime.utcnow():
        emit('error', {'msg': 'You are muted.'})
        return
    text = profanity.censor(text)
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        emit('error', {'msg': 'Room not found.'})
        return
    msg = Message(room_id=room.id, user_id=current_user.id, text=text, media=data.get('media'))
    db.session.add(msg)
    db.session.commit()
    payload = {
        'id': msg.id,
        'user': current_user.username,
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


# --- Run ---
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
