# -*- coding: utf-8 -*-

import hashlib
import time
import json
from textwrap import dedent
from collections import OrderedDict
from django.conf import settings
from edxmako.shortcuts import render_to_string
from shoppingcart.processors.exceptions import *
from shoppingcart.models import Order


def process_postpay_callback(params):
    try:
        result = payment_accepted(params)
        if result['accepted']:
          record_purchase(params, result['order'])
          #TODO : stocker le transaction_id quelque part ?
          return {'success': True,
                  'order': result['order'],
                  'error_html' : ''}
        return {'success': False,
                'order': result['order'],
                'error_html' : format_error_to_html(result['message'])}
    except CCProcessorException as error:
        return {'success': False,
                'order': None,
                'error_html' : format_error_to_html(error.message)}


def render_purchase_form_html(cart, user, cart_items):
    """
    Renders the HTML of the hidden POST form that must be used to initiate a purchase with Be2Bill
    """
    return render_to_string('shoppingcart/be2bill_form.html', {
            'action': get_purchase_endpoint(),
            'params': get_purchase_params(cart, user, cart_items),
           })


def b2bill_signature(params):
    be2bill_secret = settings.CC_PROCESSOR['Be2Bill'].get('PASSWORD', '')
    signature = be2bill_secret.join([u'{key}={value}'.format(key=k, value=v) for k, v in params.items()])
    signature = u'{secret}{signature}{secret}'.format(secret=be2bill_secret, signature=signature)
    return hashlib.sha256(signature.encode('utf-8')).hexdigest()


def get_purchase_params(cart, user, cart_items):
    total_cost = cart.total_cost
    amount = int(total_cost) * 100
    params = OrderedDict()
    params['AMOUNT'] = amount
    params['CLIENTIDENT'] = user.id
    params['DESCRIPTION'] =  u','.join([item.line_desc for item in cart_items])
    params['IDENTIFIER'] = settings.CC_PROCESSOR['Be2Bill'].get('IDENTIFIER', '')
    params['OPERATIONTYPE'] = 'payment'
    params['ORDERID'] = '{cartid}-{timestamp}'.format(cartid=cart.id, timestamp=unicode(time.time()).split('.')[0])
    params['VERSION'] = '2.0'
    params['HASH'] = b2bill_signature(params)
    return params


def get_purchase_endpoint():
    # TODO : url de rechange
    return settings.CC_PROCESSOR['Be2Bill'].get('PURCHASE_ENDPOINT', '')


def payment_accepted(params):
    for key in ['OPERATIONTYPE', 'EXECCODE', 'MESSAGE']:
        if key not in params:
            raise CCProcessorDataException("La réponse de Be2Bill est incomplète, le paramètre {param} est manquant."
                .format(param=key))

    if params['EXECCODE'] not in REASONCODE_MAP:
        raise CCProcessorDataException("Le code de réponse de Be2Bill est inconnu")

    try:
        order = Order.objects.get(id=params['ORDERID'].split('-')[0])
    except Order.DoesNotExist:
        raise CCProcessorDataException(_("The payment processor accepted an order whose number is not in our system."))

    if REASONCODE_MAP[params['EXECCODE']] == "accepted":
        if not 'TRANSACTIONID' in params:
            raise CCProcessorDataException("Le paramètre TRANSACTIONID est manquant")
        return {'accepted': True,
                'code': params['EXECCODE'],
                'message': REASONCODE_MAP[params['EXECCODE']],
                'transaction_id': params['TRANSACTIONID'],
                'order': order}
    return {'accepted': False,
            'code': params['EXECCODE'],
            'message': REASONCODE_MAP[params['EXECCODE']],
            'transaction_id': params['TRANSACTIONID'] if 'TRANSACTIONID' in params else None,
            'order': order}


def record_purchase(params, order):
    """
    Record the purchase and run purchased_callbacks
    """
    order.purchase(
        first='',
        last='',
        street1='',
        street2='',
        city='',
        state='',
        country='',
        postalcode='',
        ccnum='',
        cardtype='',
        processor_reply_dump=json.dumps(params)
    )


def format_error_to_html(message):
    msg = dedent(
            """
            <p class=error-msg">
            Nous sommes désolé mais une erreur est survenue. <span class="exception-msg">{msg}</span>
            <br />
            Si vous avez des questions ou des réclamations à faire concernant un paiement, contactez-nous
            <a href="https://courses.ionis-group.com/contact">ici</a>
            </p>
            """.format(msg=message))
    return msg


REASONCODE_MAP = {'0000': "accepted",
                  '0001': "accepted",
                  '1001': "La transaction a échoué, un champs est manquant.",
                  '1002': "La transaction a échoué, un champs est invalide.",
                  '1003': "La transaction a échoué, la signature Be2Bill est invalide.",
                  '1004': "La transaction a échoué, le protocole mentionné n'est pas supporté.",
                  '1005': "La transaction a échoué, une erreur interne est survenue.",
                  '3001': "La transaction a échoué, votre compte est désactivé. Veuillez contacter le support technique de Be2Bill.",
                  '3002': "La transaction a échoué, l'adresse IP du serveur n'est pas autorisée. Vérifiez votre configuration sur l'extranet Be2Bill.",
                  '3003': "La transaction a échoué, la transaction demandée n'est pas autorisée. Veuillez contacter le support technique de Be2Bill.",
                  '4001': "La transaction a échoué, votre réseau bancaire l'a refusée.",
                  '4002': "La transaction a échoué, vos fonds sont insuffisants pour réaliser le paiement.",
                  '4003': "La transaction a échoué, votre carte bancaire a été refusée.",
                  '4004': "La transaction a été interrompue.",
                  '4005': "La transaction a échoué pour cause de suspicion de fraude.",
                  '4006': "La transaction a échoué, cette carte a été déclarée perdue.",
                  '4007': "La transaction a échoué, cette carte a été déclarée volée.",
                  '4008': "La transaction a échoué, l'authentification 3DSecure a échoué.",
                  '4009': "La transaction a échoué, l'authentification 3DSecure a expiré.",
                  '4010': "La transaction a échoué car des données sont invalides.",
                  '4011': "La transaction a échoué, elle a déjà été traitée.",
                  '4012': "La transaction a échoué, vos données bancaires sont invalides.",
                  '4013': "La transaction a échoué, votre réseau bancaire l'a refusé.",
                  '5001': "La transaction a échoué, le service est temporairement indisponible. Veuillez réessayer dans les prochaines minutes.",
                  '5002': "La transaction a échoué, le réseau bancaire est temporairement indisponible. Veuillez réessayer dans les prochaines minutes.",
                  '5003': "La transaction a échoué, le service est actuellement en maintenance. Veuillez réessayer dans les prochaines minutes.",
                  '5004': "La transaction a échoué, le service est temporairement indisponible. Veuillez réessayer dans les prochaines minutes.",
                  '6001': "La transaction a échoué pour cause de suspicion de fraude.",
                  '6002': "La transaction a échoué pour cause de suspicion de fraude.",
                  '6003': "La transaction a échoué, le porteur de la carte bancaire a déjà contesté une transaction.",
                  '6004': "La transaction a échoué pour cause de suspicion de fraude.",
                }