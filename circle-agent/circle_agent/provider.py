class CircleProvider:

    name = 'provider'

    def wallet_balance(self, organization_id, wallet_id):
        raise NotImplementedError()

    def transfer_quote(self, organization_id, wallet_id, amount, asset, chain, destination):
        raise NotImplementedError()

    def screen_transfer(self, organization_id, wallet_id, amount, asset, chain, destination):
        raise NotImplementedError()

    def submit_transfer(self, action):
        raise NotImplementedError()

    def transaction_status(self, organization_id, transaction_id):
        raise NotImplementedError()
