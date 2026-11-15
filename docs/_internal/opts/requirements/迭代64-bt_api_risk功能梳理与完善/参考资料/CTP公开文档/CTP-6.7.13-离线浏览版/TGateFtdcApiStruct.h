#if !defined(TGATE_FTDCSTRUCT_H)
#define TGATE_FTDCSTRUCT_H

#if _MSC_VER > 1000
#pragma once
#endif // _MSC_VER > 1000

#include "TGateFtdcApiDataType.h"

///服务地址查询
struct CTGateFtdcQryTGIpAddrParamField
{
	///经纪公司代码
	TTGateFtdcBrokerIDType BrokerID;
	///用户代码
	TTGateFtdcUserIDType   UserID;
	///APP代码
	TTGateFtdcAppIDType   AppID;
};

///服务地址参数
struct CTGateFtdcTGIpAddrParamField
{
	///经纪公司代码
	TTGateFtdcBrokerIDType	BrokerID;
	///用户代码
	TTGateFtdcUserIDType   UserID;
	///服务地址
	TTGateFtdcIpAddrType	Address;
	///交易中心代码
	TTGateFtdcDRIdentityIDType	DRIdentityID;
	///交易中心名称
	TTGateFtdcDRIdentityNameType	DRIdentityName;
	///交易地址OR行情地址
	TTGateFtdcAddrSrvModeType	AddrSrvMode;
	///地址版本
	TTGateFtdcAddrVerType	AddrVer;
	///服务地址编号
	TTGateFtdcCommonIntType	AddrNo;
	///服务地址名称
	TTGateFtdcAddrNameType	AddrName;
	///是否是国密地址
	TTGateFtdcBoolType	IsSM;
	///是否是内网地址
	TTGateFtdcBoolType	IsLocalAddr;
	///地址补充信息
	TTGateFtdcAddrRemarkType	Remark;
	///站点
	TTGateFtdcSiteType	Site;
	///网络运营商，枚举值有：电信、移动、联通、广电、铁通、卫通、其他
	TTGateFtdcNetOperatorType	NetOperator;
	///系统名称，枚举值有：上期CTP、上期CTPMini、上期CTP股票期权、恒生UFX、恒生UFT2.0、飞马开放柜台、
	///飞创DCE X-One、飞创X-SPEED、金仕达B2C、金仕达B2B、金仕达DTP-F、易盛启明星、其他
	TTGateFtdcAddrNameType	SysName;
};

struct CTGateFtdcRspInfoField
{
	///错误代码
	TTGateFtdcErrorIDType	ErrorID;
	///错误信息
	TTGateFtdcErrorMsgType	ErrorMsg;
};

#endif