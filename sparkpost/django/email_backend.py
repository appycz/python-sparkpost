from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

from sparkpost import SparkPost
from sparkpost.exceptions import SparkPostAPIException

from .exceptions import UnsupportedParam, UnsupportedContent, InvalidStoredTemplate, InvalidInlineTemplate


class SparkPostEmailBackend(BaseEmailBackend):
    """
    SparkPost wrapper for Django email backend
    """

    def __init__(self, fail_silently=False, **kwargs):
        super(SparkPostEmailBackend, self)\
            .__init__(fail_silently=fail_silently, **kwargs)

        sp_api_key = getattr(settings, 'SPARKPOST_API_KEY', None)

        self.client = SparkPost(sp_api_key)

    def send_messages(self, email_messages):
        """
        Send emails, returns integer representing number of successful emails
        """
        success = 0
        for message in email_messages:
            try:
                response = self._send(message)
                success += response['total_accepted_recipients']
            except Exception:
                if not self.fail_silently:
                    raise
        return success

    def _send(self, message):
        self.check_unsupported(message)
        self.check_attachments(message)

        params = dict(
            recipients=message.to,
            from_email=message.from_email,
            subject=message.subject,
            text=message.body,
        )

        sparkpost_cfg = getattr(message, 'sparkpost', None)

        if sparkpost_cfg:
            self.check_inline_template(sparkpost_cfg)

            if sparkpost_cfg.get('template'):
                params.pop('text', None)

            params.update(sparkpost_cfg)

        if hasattr(message, 'alternatives') and len(message.alternatives) > 0:
            for alternative in message.alternatives:

                if alternative[1] == 'text/html':
                    params['html'] = alternative[0]
                else:
                    raise UnsupportedContent(
                        'Content type %s is not supported' % alternative[1]
                    )

        try:
            return self.client.transmissions.send(**params)
        except SparkPostAPIException as e:
            if any(err['code'] == '1603' for err in e.errors):
                raise InvalidStoredTemplate(e)
            raise

    @staticmethod
    def check_attachments(message):
        if len(message.attachments):
            raise UnsupportedContent(
                'The SparkPost Django email backend does not '
                'currently support attachment.'
            )

    @staticmethod
    def check_unsupported(message):
        unsupported_params = ['cc', 'bcc', 'reply_to']
        for param in unsupported_params:
            if len(getattr(message, param, [])):
                raise UnsupportedParam(
                    'The SparkPost Django email backend does not currently '
                    'support %s.' % param
                )

    @staticmethod
    def check_inline_template(sparkpost_cfg):
        if ('html' in sparkpost_cfg) != ('text' in sparkpost_cfg):  # xor
            raise InvalidInlineTemplate("Both 'html' and 'text' must be present in 'EmailMessage.sparkpost'")

