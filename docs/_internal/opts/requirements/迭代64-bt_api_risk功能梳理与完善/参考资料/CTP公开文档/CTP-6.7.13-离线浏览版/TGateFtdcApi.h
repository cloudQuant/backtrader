#if !defined(TGATE_FTDCAPI_H)
#define TGATE_FTDCAPI_H

#if _MSC_VER > 1000
#pragma once
#endif // _MSC_VER > 1000

#if defined(TGAPI_IS_LIB) && defined(WIN32)
#ifdef LIB_TG_API_EXPORT
#define TG_API_EXPORT __declspec(dllexport)
#else
#define TG_API_EXPORT __declspec(dllimport)
#endif
#else
#define TG_API_EXPORT 
#endif

#include "TGateFtdcApiStruct.h"

class CTGateFtdcSpi
{
public:
	///错误应答
	virtual void OnRspError(CTGateFtdcRspInfoField* pRspInfo, int nRequestID, bool bIsLast) {};

	///服务地址参数查询响应
	virtual void OnRspQryTGIpAddrParam(CTGateFtdcTGIpAddrParamField* pTGIpAddrParam, CTGateFtdcRspInfoField* pRspInfo, int nRequestID, bool bIsLast) {};
};


class TG_API_EXPORT CTGateFtdcApi
{
public:
	///创建TGApi
	///@param bIsProductionMode true:使用生产版本的API  false:使用测评版本的API
	static CTGateFtdcApi* CreateTGateFtdcApi(bool bIsProductionMode = true);

	///获取API的版本信息
	///@retrun 获取到的版本号
	static const char* GetApiVersion();

	///删除接口对象本身
	///@remark 不再使用本接口对象时,调用该函数删除接口对象
	virtual void Release() = 0;

	///等待接口线程结束运行
	///@return 线程退出代码
	virtual int Join() = 0;

	///注册TGATE网络地址
	///@param pszTGAddress：TGATE网络地址。
	///@remark 网络地址的格式为：“protocol://ipaddress:port”，如：”tcp://127.0.0.1:17001”。 
	///@remark “tcp”代表传输协议，“127.0.0.1”代表服务器地址。”17001”代表服务器端口号。
	virtual void RegisterTGAddr(char* pszTGAddress) = 0;

	///注册回调接口
	///@param pSpi 派生自回调接口类的实例
	virtual void RegisterSpi(CTGateFtdcSpi* pSpi) = 0;

	///服务地址参数查询
	/// 返回值：
	/// -1：入参出错
	/// -2：超过在途流控
	/// -3：超过频率流控 
	virtual int ReqQryTGIpAddrParam(CTGateFtdcQryTGIpAddrParamField* pQryTGIpAddrParamField,int nRequestID) = 0;

protected:
	~CTGateFtdcApi() {};
};
#endif