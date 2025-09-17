from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, EqualTo, Length

class RegisterForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    name = StringField("Full name", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=200)])
    nickname = StringField("Nickname", validators=[DataRequired(), Length(max=80)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=30)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField("Register")

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class ProfileForm(FlaskForm):
    name = StringField("Full name")
    nickname = StringField("Nickname")
    bio = TextAreaField("Bio")
    submit = SubmitField("Save")
