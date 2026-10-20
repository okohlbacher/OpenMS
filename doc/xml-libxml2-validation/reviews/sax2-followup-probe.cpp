#include <OpenMS/FORMAT/XMLFile.h>
#include <OpenMS/FORMAT/HANDLERS/XMLHandler.h>
#include <OpenMS/FORMAT/HANDLERS/XMLAttributes.h>
#include <cassert>
#include <iostream>
struct R:OpenMS::Internal::XMLFile {using XMLFile::parseBuffer_;};
struct H:OpenMS::Internal::XMLHandler {
 H():XMLHandler("memory","1"){};
 std::u16string value,xmlns; std::vector<std::u16string> starts,ends;
 void onStartElement(const char16_t*n,const OpenMS::Internal::XMLAttributes&a)override{starts.emplace_back(n);if(auto p=a.value("p:value"))value=p;if(auto p=a.value("xmlns"))xmlns=p;}
 void onEndElement(const char16_t*n)override{ends.emplace_back(n);}
};
int main(){R r;H h;r.parseBuffer_("<!DOCTYPE root [<!ENTITY e 'ENTITY'>]><root xmlns='urn:one' xmlns:p='urn:p'><p:child p:value='"+std::string(70000,'x')+" é&#x1F9EC;&amp;&e;' next='sentinel'/><child xmlns=''/></root>",&h,true);assert(h.value==std::u16string(70000,u'x')+u" é🧬&ENTITY");assert(h.xmlns.empty());assert((h.starts==std::vector<std::u16string>{u"root",u"p:child",u"child"}));assert((h.ends==std::vector<std::u16string>{u"p:child",u"child",u"root"}));std::cout<<"SAX2 independent cross-chunk bounded-attribute/entity/namespace checks passed\n";}
