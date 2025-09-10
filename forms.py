from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, BooleanField, FileField, SubmitField, SelectField
from wtforms.validators import DataRequired, Length, EqualTo, Email

class RegisterForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    username = StringField("Nickname", validators=[DataRequired(), Length(min=3, max=80)])
    phone = StringField("Phone")
    gender = SelectField("Gender", choices=[("", "Select"), ("Male","Male"), ("Female","Female"), ("Other","Other")])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Register")

class LoginForm(FlaskForm):
    username = StringField("Nickname or Email", validators=[DataRequired()])
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
