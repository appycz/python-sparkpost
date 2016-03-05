import pytest
import mock
from distutils.version import StrictVersion

from django import get_version
from django.conf import settings
from django.core.mail import send_mail
from django.core.mail import send_mass_mail
from django.core.mail import EmailMessage
from django.core.mail import EmailMultiAlternatives

from sparkpost.django.email_backend import SparkPostEmailBackend
from sparkpost.django.exceptions import UnsupportedParam, InvalidStoredTemplate, InvalidInlineTemplate
from sparkpost.django.exceptions import UnsupportedContent
from sparkpost.exceptions import SparkPostAPIException
from sparkpost.transmissions import Transmissions

try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

API_KEY = 'API_Key'

settings.configure(
    DEBUG=True,
    EMAIL_BACKEND='sparkpost.django.email_backend.SparkPostEmailBackend',
    SPARKPOST_API_KEY=API_KEY
)


def at_least_version(version):
    return StrictVersion(get_version()) > StrictVersion(version)


def get_params(overrides=None):
    if overrides is None:
        overrides = {}

    defaults = {
        'subject': 'test subject',
        'message': 'test body',
        'from_email': 'from@example.com',
        'recipient_list': ['to@example.com'],
    }

    params = defaults.copy()
    params.update(overrides)
    return params


def mailer(params):
    return send_mail(**params)


def test_password_retrieval():
    backend = SparkPostEmailBackend()
    assert backend.client.api_key == API_KEY


def test_fail_silently():
    # should not raise
    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.side_effect = Exception('i should not be raised')
        mailer(get_params({'fail_silently': True}))

    # should raise
    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.side_effect = Exception('i should be raised')
        with pytest.raises(Exception):
            mailer(get_params())


def test_successful_sending():
    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.return_value = {'total_accepted_recipients': 1,
                                  'total_rejected_recipients': 2}

        result = mailer(get_params({
            'recipient_list': ['to1@example.com', 'to2@example.com'],
            'fail_silently': True
        }))
        assert result == 1

    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.return_value = {'total_accepted_recipients': 10,
                                  'total_rejected_recipients': 2}

        result = mailer(
            get_params(
                {'recipient_list': ['to1@example.com', 'to2@example.com'],
                 'fail_silently': True
                 }
            ))

        assert result == 10


def test_send_number_of_emails_correctly():
    with mock.patch.object(Transmissions, 'send') as mock_send:
        mailer(get_params({
            'recipient_list': ['to1@example.com', 'to2@example.com'],
            'fail_silently': True
        }))
        assert mock_send.call_count == 1

    with mock.patch.object(Transmissions, 'send') as mock_send:
        message1 = ('message 1 subject', 'message 1 body', 'from@example.com',
                    ['to1@example.com'])
        message2 = ('message 2 subject', 'message 2 body', 'from@example.com',
                    ['to2@example.com'])
        message3 = ('message 3 subject', 'message 3 body', 'from@example.com',
                    ['to3@example.com'])

        send_mass_mail((message1, message2, message3), fail_silently=False)
        assert mock_send.call_count == 3


def test_params():
    recipients = ['to1@example.com', 'to2@example.com']
    with mock.patch.object(Transmissions, 'send'):
        mailer(get_params(
            {'recipient_list': recipients,
             'fail_silently': True
             }
        ))

        Transmissions.send.assert_called_with(recipients=recipients,
                                              text='test body',
                                              from_email='from@example.com',
                                              subject='test subject'
                                              )


def test_content_types():
    def new_send(**kwargs):
        assert kwargs['text'] == 'hello there'
        assert kwargs['html'] == '<p>Hello There</p>'

        return {
            'total_accepted_recipients': 0,
            'total_rejected_recipients': 0
        }

    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.side_effect = new_send
        send_mail(
            'test subject',
            'hello there',
            'from@example.com',
            ['to@example.com'],
            html_message='<p>Hello There</p>'
        )


def test_unsupported_content_types():
    params = get_params()

    with pytest.raises(UnsupportedContent):
        mail = EmailMultiAlternatives(
            params['subject'],
            'plain text',
            params['from_email'],
            params['recipient_list'])
        mail.attach_alternative('<ppp>non-plain content</ppp>', 'text/alien')
        mail.send()


def test_attachment():
    params = get_params()
    params['body'] = params.pop('message')
    params['to'] = params.pop('recipient_list')

    attachment = StringIO()
    attachment.write('hello file')
    email = EmailMessage(**params)
    email.attach('file.txt', attachment, 'text/plain')

    with pytest.raises(UnsupportedContent):
        email.send()


def test_cc_bcc_reply_to():
    params = get_params({
        'cc': ['cc1@example.com', 'cc2@example.com']
    })
    params['body'] = params.pop('message')
    params['to'] = params.pop('recipient_list')

    # test cc exception
    with pytest.raises(UnsupportedParam):
        email = EmailMessage(**params)
        email.send()
    params.pop('cc')

    # test bcc exception
    params['bcc'] = ['bcc1@example.com', 'bcc1@example.com']
    with pytest.raises(UnsupportedParam):
        email = EmailMessage(**params)
        email.send()
    params.pop('bcc')

    if at_least_version('1.8'):  # reply_to is supported from django 1.8
        # test reply_to exception
        params['reply_to'] = ['devnull@example.com']
        with pytest.raises(UnsupportedParam):
            email = EmailMessage(**params)
            email.send()
        params.pop('reply_to')


def test_template_inline():
    def new_send(**kwargs):
        assert kwargs['subject'] == 'Some subject'
        assert kwargs['html'] == '<p>template content</>'
        assert kwargs['text'] == 'template content'
        assert kwargs['recipients'] == [{'address': {'email': 'to@example.com'},
                                         'substitution_data': {'recipient_var': 'value'}}]
        assert kwargs['substitution_data'] == {
            'global_var': 'value'
        }

        return {
            'total_accepted_recipients': 0,
            'total_rejected_recipients': 0
        }

    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.side_effect = new_send
        email = EmailMessage(
            subject='Some subject', from_email="from@example.com",
            to=[{'address': {'email': 'to@example.com'},
                 'substitution_data': {'recipient_var': 'value'}}]
        )
        email.sparkpost = {
            'html': '<p>template content</>',
            'text': 'template content',
            'substitution_data': {
                'global_var': 'value'
            }
        }
        email.send()


def test_template_inline_missing():
    def new_send(**kwargs):
        assert kwargs['subject'] == 'Some subject'
        assert kwargs['text'] == 'template content'
        assert kwargs['recipients'] == [{'address': {'email': 'to@example.com'},
                                         'substitution_data': {'recipient_var': 'value'}}]
        assert kwargs['substitution_data'] == {
            'global_var': 'value'
        }

        return {
            'total_accepted_recipients': 0,
            'total_rejected_recipients': 0
        }

    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.side_effect = new_send
        email = EmailMessage(
            subject='Some subject', from_email="from@example.com",
            to=[{'address': {'email': 'to@example.com'},
                 'substitution_data': {'recipient_var': 'value'}}]
        )
        email.sparkpost = {
            'text': 'template content',
            'substitution_data': {
                'global_var': 'value'
            }
        }

        with pytest.raises(InvalidInlineTemplate):
            email.send()


def test_template_stored():
    def new_send(**kwargs):
        assert 'text' not in kwargs
        assert kwargs['subject'] == 'Some subject'
        assert kwargs['template'] == 'stored_template'
        assert kwargs['recipients'] == [{'address': {'email': 'to@example.com'},
                                         'substitution_data': {'recipient_var': 'value'}}]
        assert kwargs['substitution_data'] == {
            'global_var': 'value'
        }

        return {
            'total_accepted_recipients': 0,
            'total_rejected_recipients': 0
        }

    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.side_effect = new_send
        email = EmailMessage(
            subject='Some subject', from_email="from@example.com",
            to=[{'address': {'email': 'to@example.com'},
                 'substitution_data': {'recipient_var': 'value'}}]
        )
        email.sparkpost = {
            'template': "stored_template",
            'substitution_data': {
                'global_var': 'value'
            }
        }
        email.send()


def test_template_stored_invalid():
    mock_resp = mock.Mock()
    mock_resp.status_code = 422
    mock_resp.json = lambda: {
        'errors': [
            {
                "message": "Subresource not found",
                "description": "template 'invalid_stored_template' does not exist",
                "code": "1603"
            }
        ]
    }

    with mock.patch.object(Transmissions, 'send') as mock_send:
        mock_send.side_effect = SparkPostAPIException(mock_resp)

        with pytest.raises(InvalidStoredTemplate):
            email = EmailMessage(
                subject='test subject', from_email="from@example.com",
                to=['to@example.com']
            )
            email.sparkpost = {'template_name': 'invalid_stored_template'}
            email.send()
