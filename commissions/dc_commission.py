import backtrader as bt
class ComminfoDC(bt.CommInfoBase):
    '''实现一个数字货币的佣金类
    '''
    params = (
        ('stocklike', False),
        ('commtype', CommInfoBase.COMM_PERC),
        ('percabs', True),
        ("interest",3),
    )

    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * price * self.p.mult * self.p.commission

    def get_margin(self, price):
        return price * self.p.mult * self.p.margin

    # 计算利息费用,这里面涉及到一些简化
    def get_credit_interest(self, data, pos, dt):
        ''' 例如我持有100U，要买300U的BTC，杠杆为三倍，这时候我只需要借入2*100U的钱就可以了，
       所以利息应该是200U * interest，同理，对于n倍开多，需要付（n-1）*base的利息
        如果我要开空，我只有100U，我必须借入BTC先卖掉，就算是一倍开空，也得借入100U的BTC，
        所以对于n倍开空，需要付n*base的利息'''
        # 仓位及价格
        size, price = pos.size, pos.price
        # 持仓时间
        dt0 = dt
        dt1 = pos.datetime
        gap_seconds = (dt0 - dt1).seconds
        days = gap_seconds / (24 * 60 * 60)
        # 计算当前的持仓价值
        position_value = size * price * self.p.mult
        # 如果当前的持仓是多头，并且持仓价值大于1倍杠杆，超过1倍杠杆的部分将会收取利息费用
        total_value = self.getvalue()
        if size > 0 and position_value > total_value:
            return days * self.self._creditrate * (position_value - total_value)
        # 如果持仓是多头，但是在一倍杠杆之内
        if size > 0 and position_value <= total_value:
            return 0
        # 如果当前是做空的交易，计算利息
        if size < 0:
            return days * self.self._creditrate * position_value




