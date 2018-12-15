"""Custom user model for the ad server"""
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils.translation import ugettext as _

from ..models import Advertiser
from ..models import Publisher


class AdServerUserManager(BaseUserManager):

    """A django query manager for our custom user model"""

    def create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError(_("Email must be set"))

        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):

    """
    The custom extensible user model for the ad server

    https://docs.djangoproject.com/en/1.11/topics/auth/customizing/#specifying-a-custom-user-model

    Inherits from both the AbstractBaseUser and PermissionMixin.
    The following attributes are inherited from the superclasses::

        * password
        * last_login
        * is_superuser
    """

    email = models.EmailField(unique=True, null=True)
    name = models.CharField(_("name"), max_length=255, default="", blank=True)
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Is the user allowed to have access to the admin"),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    updated_date = models.DateTimeField(_("update date"), auto_now=True)
    created_date = models.DateTimeField(_("create date"), auto_now_add=True)

    # A user may have access to zero or more advertisers or publishers
    advertisers = models.ManyToManyField(Advertiser, blank=True)
    publishers = models.ManyToManyField(Publisher, blank=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []  # email is required already
    objects = AdServerUserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        """Magic method override"""
        return self.email

    def get_full_name(self):
        return self.name or self.email

    def get_short_name(self):
        return self.get_full_name()
