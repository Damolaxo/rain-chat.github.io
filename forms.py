from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, BooleanField, FileField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo


class RegisterForm(FlaskForm):
    username = StringField(
        "Username", 
        validators=[DataRequired(), Length(min=3, max=80)]
    )
    password = PasswordField(
        "Password", 
        validators=[DataRequired(), Length(min=6)]
    )
    confirm = PasswordField(
        "Confirm Password", 
        validators=[DataRequired(), EqualTo("password")]
    )
    name = StringField("Name", validators=[Length(max=120)])
    submit = SubmitField("Register")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class ProfileForm(FlaskForm):
    name = StringField("Name", validators=[Length(max=120)])
    bio = TextAreaField("Bio")
    avatar = FileField("Profile Picture")  # you’ll need Flask-Uploads or similar for handling
    submit = SubmitField("Update Profile")


class RoomForm(FlaskForm):
    name = StringField("Room Name", validators=[DataRequired(), Length(max=120)])
    private = BooleanField("Private Room")
    submit = SubmitField("Create Room")
