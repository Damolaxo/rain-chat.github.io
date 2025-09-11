from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, BooleanField, FileField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, EqualTo, Email

class RegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=20)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password")])
    name = StringField("Full Name", validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    submit = SubmitField("Register")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class ProfileForm(FlaskForm):
    name = StringField("Name", validators=[Length(max=120)])
    bio = TextAreaField("Bio")
    avatar = FileField("Profile picture")
    submit = SubmitField("Update Profile")

class RoomForm(FlaskForm):
    name = StringField("Room name", validators=[DataRequired(), Length(max=120)])
    private = BooleanField("Private")
    submit = SubmitField("Create room")
