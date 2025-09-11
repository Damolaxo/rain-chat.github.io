# app.py
import eventlet
eventlet.monkey_patch()

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, send_from_directory, abort
from flask_migrate import Migrate
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, join_room, leave_room, emit
from werkzeug.utils import secure_filename
from better_profanity import profanity

# local modules - adjust names if your files differ
from models import db, User, Room, Message
from forms import RegistrationForm, LoginForm, ProfileForm, RoomForm

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "chat.db"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

# --- Extensions ---
db.init_app(app)
migrate = Migrate(app, db)

login_manager = LoginManager(app)
login_manager.login_view = "login"

socketio = SocketIO(app, cors_allowed_origins="*", manage_session=False)

profanity.load_censor_words()

# --- Helpers ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_current_year():
    return {"current_year": datetime.utcnow().year}


# --- Routes ---

@app.route("/")
def index():
    """Public landing page. If logged in, show rooms list."""
    rooms = Room.query.order_by(Room.name).all() if current_user.is_authenticated else []
    return render_template("index.html", rooms=rooms)


# Register (uses WTForms RegistrationForm)
@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        # normalize email/username
        username = form.username.data.strip()
        email = getattr(form, "email", None)
        email_val = email.data.strip() if email is not None else None

        # check existing by username OR email if provided
        existing = None
        if email_val:
            existing = User.query.filter((User.username == username) | (User.email == email_val)).first()
        else:
            existing = User.query.filter_by(username=username).first()

        if existing:
            flash("This username or email is already registered. Please log in.", "danger")
            return redirect(url_for("login"))

        # create user
        u = User(username=username)
        # set optional fields depending on form
        if hasattr(form, "name"):
            u.name = form.name.data.strip() if form.name.data else None
        if hasattr(form, "email"):
            u.email = email_val
        if hasattr(form, "phone"):
            u.phone = getattr(form, "phone").data if getattr(form, "phone", None) else None
        if hasattr(form, "gender"):
            u.gender = getattr(form, "gender").data if getattr(form, "gender", None) else None

        # password helper from your models
        u.set_password(form.password.data)
        db.session.add(u)
        db.session.commit()

        flash("✅ You have successfully registered. Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", form=form)


# Login (uses WTForms LoginForm)
@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username_or_email = form.username.data.strip()
        # try email first, then username
        user = None
        if "@" in username_or_email:
            user = User.query.filter_by(email=username_or_email).first()
        if not user:
            user = User.query.filter_by(username=username_or_email).first()

        if user and user.check_password(form.password.data):
            if user.banned:
                flash("Your account is banned.", "danger")
                return redirect(url_for("login"))
            login_user(user)
            flash("✅ You have successfully logged in!", "success")
            return redirect(url_for("chat"))
        else:
            flash("Invalid username/email or password. If you don't have an account, please register.", "danger")
            return redirect(url_for("login"))
    return render_template("login.html", form=form)


# Logout
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# Profile
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.name = form.name.data
        current_user.bio = form.bio.data
        # handle avatar upload
        f = form.avatar.data
        if f and getattr(f, "filename", None):
            filename = secure_filename(f.filename)
            path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            f.save(path)
            current_user.avatar = "uploads/" + filename
        db.session.commit()
        flash("Profile updated ✅", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=current_user, form=form)


# Chat landing
@app.route("/chat")
@login_required
def chat():
    return render_template("chat.html", username=current_user.username)


# Room view
@app.route("/room/<room_name>")
@login_required
def room(room_name):
    room = Room.query.filter_by(name=room_name).first_or_404()
    if room.private and not current_user.is_admin:
        flash("Private room - access denied 🚫", "danger")
        return redirect(url_for("chat"))
    messages = Message.query.filter_by(room_id=room.id).order_by(Message.created_at.asc()).limit(200).all()
    return render_template("chat.html", room=room, messages=messages)


# Create room
@app.route("/create_room", methods=["POST"])
@login_required
def create_room():
    form = RoomForm()
    if form.validate_on_submit():
        if Room.query.filter_by(name=form.name.data).first():
            flash("⚠️ Room already exists.", "danger")
            return redirect(url_for("chat"))
        r = Room(name=form.name.data.strip(), private=form.private.data)
        db.session.add(r)
        db.session.commit()
        flash("✅ Room created successfully!", "success")
        return redirect(url_for("room", room_name=r.name))
    flash("❌ Room creation failed.", "danger")
    return redirect(url_for("chat"))


# Serve uploaded files (profile pics / media)
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


# --- Socket.IO handlers ---
@socketio.on("join")
def handle_join(data):
    room_name = data.get("room")
    if room_name:
        join_room(room_name)
        emit("system_message", {"msg": f"{current_user.username} joined {room_name}"}, room=room_name)


@socketio.on("leave")
def handle_leave(data):
    room_name = data.get("room")
    if room_name:
        leave_room(room_name)
        emit("system_message", {"msg": f"{current_user.username} left {room_name}"}, room=room_name)


@socketio.on("send_message")
def handle_message(data):
    text = (data.get("text") or "").strip()
    room_name = data.get("room")
    if not text and not data.get("media"):
        return
    if current_user.is_anonymous:
        emit("error", {"msg": "Authentication required."})
        return
    if current_user.banned:
        emit("error", {"msg": "You are banned."})
        return
    if current_user.muted_until and current_user.muted_until > datetime.utcnow():
        emit("error", {"msg": "You are muted."})
        return

    text = profanity.censor(text)
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        emit("error", {"msg": "Room not found."})
        return

    msg = Message(room_id=room.id, user_id=current_user.id, text=text, media=data.get("media"))
    db.session.add(msg)
    db.session.commit()

    payload = {
        "id": msg.id,
        "user": current_user.username,
        "avatar": current_user.avatar,
        "text": text,
        "media": msg.media,
        "created_at": msg.created_at.isoformat(),
    }
    emit("new_message", payload, room=room_name)


# --- Admin actions ---
@app.route("/admin/ban/<int:user_id>")
@login_required
def admin_ban(user_id):
    if not current_user.is_admin:
        abort(403)
    u = User.query.get_or_404(user_id)
    u.banned = True
    db.session.commit()
    flash("User banned 🚫", "info")
    return redirect(url_for("chat"))


@app.route("/admin/unban/<int:user_id>")
@login_required
def admin_unban(user_id):
    if not current_user.is_admin:
        abort(403)
    u = User.query.get_or_404(user_id)
    u.banned = False
    db.session.commit()
    flash("User unbanned ✅", "info")
    return redirect(url_for("chat"))


@app.route("/admin/mute/<int:user_id>")
@login_required
def admin_mute(user_id):
    if not current_user.is_admin:
        abort(403)
    u = User.query.get_or_404(user_id)
    u.muted_until = datetime.utcnow() + timedelta(minutes=30)
    db.session.commit()
    flash("User muted for 30 minutes 🔇", "info")
    return redirect(url_for("chat"))


# --- Run ---
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
